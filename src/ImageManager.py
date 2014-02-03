# for localized messages
from boxbranding import getBoxType, getImageVersion, getImageBuild, getMachineBrand, getMachineName
from os import path, system, mkdir, makedirs, listdir, remove, statvfs, chmod, walk, symlink
from shutil import rmtree, move, copy
from time import localtime, time, strftime, mktime

from enigma import eTimer

from . import _
import Components.Task
from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.Button import Button
from Components.MenuList import MenuList
from Components.config import config, ConfigSubsection, ConfigYesNo, ConfigSelection, ConfigText, ConfigNumber, NoSave, ConfigClock
from Components.Harddisk import harddiskmanager, getProcMounts
from Screens.Screen import Screen
from Screens.Setup import Setup
from Components.Console import Console
from Screens.MessageBox import MessageBox
from Screens.Standby import TryQuitMainloop
from Tools.Notifications import AddPopupWithCallback
import process

RAMCHEKFAILEDID = 'RamCheckFailedNotification'

hddchoises = []
for p in harddiskmanager.getMountedPartitions():
	if path.exists(p.mountpoint):
		d = path.normpath(p.mountpoint)
		if p.mountpoint != '/':
			hddchoises.append((p.mountpoint, d))
config.imagemanager = ConfigSubsection()
config.imagemanager.folderprefix = ConfigText(default=getBoxType(), fixed_size=False)
config.imagemanager.backuplocation = ConfigSelection(choices = hddchoises)
config.imagemanager.schedule = ConfigYesNo(default = False)
config.imagemanager.scheduletime = ConfigClock(default = 0) # 1:00
config.imagemanager.repeattype = ConfigSelection(default = "daily", choices = [("daily", _("Daily")), ("weekly", _("Weekly")), ("monthly", _("30 Days"))])
config.imagemanager.backupretry = ConfigNumber(default = 30)
config.imagemanager.backupretrycount = NoSave(ConfigNumber(default = 0))
config.imagemanager.nextscheduletime = NoSave(ConfigNumber(default = 0))
config.imagemanager.restoreimage = NoSave(ConfigText(default=getBoxType(), fixed_size=False))

autoImageManagerTimer = None

if path.exists(config.imagemanager.backuplocation.value + 'imagebackups/imagerestore'):
	rmtree(config.imagemanager.backuplocation.value + 'imagebackups/imagerestore')

def ImageManagerautostart(reason, session=None, **kwargs):
	"""called with reason=1 to during /sbin/shutdown.sysvinit, with reason=0 at startup?"""
	global autoImageManagerTimer
	global _session
	now = int(time())
	if reason == 0:
		print "[ImageManager] AutoStart Enabled"
		if session is not None:
			_session = session
			if autoImageManagerTimer is None:
				autoImageManagerTimer = AutoImageManagerTimer(session)
	else:
		if autoImageManagerTimer is not None:
			print "[ImageManager] Stop"
			autoImageManagerTimer.stop()

class VIXImageManager(Screen):
	def __init__(self, session):
		Screen.__init__(self, session)
		Screen.setTitle(self, _("Image Manager"))

		self['lab1'] = Label()
		self["backupstatus"] = Label()
		self["key_blue"] = Button(_("Restore"))
		self["key_green"] = Button()
		self["key_yellow"] = Button(_("Downloads"))
		self["key_red"] = Button(_("Delete"))

		self.BackupRunning = False
		self.onChangedEntry = [ ]
		self.emlist = []
		self['list'] = MenuList(self.emlist)
		self.populate_List()
		self.activityTimer = eTimer()
		self.activityTimer.timeout.get().append(self.backupRunning)
		self.activityTimer.start(10)

		if BackupTime > 0:
			t = localtime(BackupTime)
			backuptext = _("Next Backup: ") + strftime(_("%a %e %b  %-H:%M"), t)
		else:
			backuptext = _("Next Backup: ")
		self["backupstatus"].setText(str(backuptext))
		if not self.selectionChanged in self["list"].onSelectionChanged:
			self["list"].onSelectionChanged.append(self.selectionChanged)

	def createSummary(self):
		from Screens.PluginBrowser import PluginBrowserSummary
		return PluginBrowserSummary

	def selectionChanged(self):
		item = self["list"].getCurrent()
		desc = self["backupstatus"].text
		if item:
			name = item
		else:
			name = ""
		for cb in self.onChangedEntry:
			cb(name, desc)

	def backupRunning(self):
		self.populate_List()
		self.BackupRunning = False
		for job in Components.Task.job_manager.getPendingJobs():
			if job.name.startswith(_("Image Manager")):
				self.BackupRunning = True
		if self.BackupRunning:
			self["key_green"].setText(_("View Progress"))
		else:
			self["key_green"].setText(_("New Backup"))
		self.activityTimer.startLongTimer(5)

	def refreshUp(self):
		self.refreshList()
		if self['list'].getCurrent():
			self["list"].instance.moveSelection(self["list"].instance.moveUp)

	def refreshDown(self):
		self.refreshList()
		if self['list'].getCurrent():
			self["list"].instance.moveSelection(self["list"].instance.moveDown)

	def refreshList(self):
		images = listdir(self.BackupDirectory)
		self.oldlist = images
		del self.emlist[:]
		for fil in images:
			if fil.endswith('.zip') or path.isdir(path.join(self.BackupDirectory, fil)):
				self.emlist.append(fil)
		self.emlist.sort()
		self.emlist.reverse()
		self["list"].setList(self.emlist)
		self["list"].show()

	def getJobName(self, job):
		return "%s: %s (%d%%)" % (job.getStatustext(), job.name, int(100*job.progress/float(job.end)))

	def showJobView(self, job):
		from Screens.TaskView import JobView
		Components.Task.job_manager.in_background = False
		self.session.openWithCallback(self.JobViewCB, JobView, job, cancelable = False, backgroundable = False, afterEventChangeable = False, afterEvent="close")

	def JobViewCB(self, in_background):
		Components.Task.job_manager.in_background = in_background

	def populate_List(self):
		imparts = []
		for p in harddiskmanager.getMountedPartitions():
			if path.exists(p.mountpoint):
				d = path.normpath(p.mountpoint)
				if p.mountpoint != '/':
					imparts.append((p.mountpoint, d))
		config.imagemanager.backuplocation.setChoices(imparts)

		if config.imagemanager.backuplocation.value.endswith('/'):
			mount = config.imagemanager.backuplocation.value, config.imagemanager.backuplocation.value[:-1]
		else:
			mount = config.imagemanager.backuplocation.value+'/', config.imagemanager.backuplocation.value
		hdd = '/media/hdd/','/media/hdd'
		if mount not in config.imagemanager.backuplocation.choices.choices:
			if hdd in config.imagemanager.backuplocation.choices.choices:
				self['myactions'] = ActionMap(['ColorActions', 'OkCancelActions', 'DirectionActions', "MenuActions", "HelpActions"],
					{
						"ok": self.keyResstore,
						'cancel': self.close,
						'red': self.keyDelete,
						'green': self.GreenPressed,
						'yellow': self.doDownload,
						'blue': self.keyResstore,
						"menu": self.createSetup,
						"up": self.refreshUp,
						"down": self.refreshDown,
						"displayHelp": self.doDownload,
					}, -1)

				self.BackupDirectory = '/media/hdd/imagebackups/'
				config.imagemanager.backuplocation.value = '/media/hdd/'
				config.imagemanager.backuplocation.save()
				self['lab1'].setText(_("The chosen location does not exist, using /media/hdd") + "\n" + _("Select an image to restore:"))
			else:
				self['myactions'] = ActionMap(['ColorActions', 'OkCancelActions', 'DirectionActions', "MenuActions"],
					{
						'cancel': self.close,
						"menu": self.createSetup,
					}, -1)

				self['lab1'].setText(_("Device: None available") + "\n" + _("Select an image to restore:"))
		else:
			self['myactions'] = ActionMap(['ColorActions', 'OkCancelActions', 'DirectionActions', "MenuActions", "HelpActions"],
				{
					'cancel': self.close,
					'red': self.keyDelete,
					'green': self.GreenPressed,
					'yellow': self.doDownload,
					'blue': self.keyResstore,
					"menu": self.createSetup,
					"up": self.refreshUp,
					"down": self.refreshDown,
					"displayHelp": self.doDownload,
					"ok": self.keyResstore,
				}, -1)

			self.BackupDirectory = config.imagemanager.backuplocation.value + 'imagebackups/'
			s = statvfs(config.imagemanager.backuplocation.value)
			free = (s.f_bsize * s.f_bavail)/(1024*1024)
			self['lab1'].setText(_("Device: ") + config.imagemanager.backuplocation.value + ' ' + _('Free space:') + ' ' + str(free) + _('MB') + "\n" + _("Select an image to restore:"))

		try:
			if not path.exists(self.BackupDirectory):
				mkdir(self.BackupDirectory, 0755)
			if path.exists(self.BackupDirectory + config.imagemanager.folderprefix.value + '-swapfile_backup'):
				system('swapoff ' + self.BackupDirectory + config.imagemanager.folderprefix.value + '-swapfile_backup')
				remove(self.BackupDirectory + config.imagemanager.folderprefix.value + '-swapfile_backup')
			self.refreshList()
		except:
			self['lab1'].setText(_("Device: ") + config.imagemanager.backuplocation.value + "\n" + _("there was a problem with this device, please reformat and try again."))

	def createSetup(self):
		self.session.openWithCallback(self.setupDone, Setup, 'viximagemanager', 'SystemPlugins/ViX')

	def doDownload(self):
		self.session.openWithCallback(self.populate_List, ImageManagerDownload, self.BackupDirectory)

	def setupDone(self, test=None):
		self.populate_List()
		self.doneConfiguring()

	def doneConfiguring(self):
		now = int(time())
		if config.imagemanager.schedule.value:
			if autoImageManagerTimer is not None:
				print "[ImageManager] Backup Schedule Enabled at", strftime("%c", localtime(now))
				autoImageManagerTimer.backupupdate()
		else:
			if autoImageManagerTimer is not None:
				global BackupTime
				BackupTime = 0
				print "[ImageManager] Backup Schedule Disabled at", strftime("%c", localtime(now))
				autoImageManagerTimer.backupstop()
		if BackupTime > 0:
			t = localtime(BackupTime)
			backuptext = _("Next Backup: ") + strftime(_("%a %e %b  %-H:%M"), t)
		else:
			backuptext = _("Next Backup: ")
		self["backupstatus"].setText(str(backuptext))

	def keyDelete(self):
		self.sel = self['list'].getCurrent()
		if self.sel:
			message = _("Are you sure you want to delete this backup:\n ") + self.sel
			ybox = self.session.openWithCallback(self.doDelete, MessageBox, message, MessageBox.TYPE_YESNO, default = False)
			ybox.setTitle(_("Remove Confirmation"))
		else:
			self.session.open(MessageBox, _("You have no image to delete."), MessageBox.TYPE_INFO, timeout = 10)

	def doDelete(self, answer):
		if answer is True:
			self.sel = self['list'].getCurrent()
			self["list"].instance.moveSelectionTo(0)
			if self.sel.endswith('.zip'):
				remove(self.BackupDirectory + self.sel)
			else:
				rmtree(self.BackupDirectory + self.sel)
		self.populate_List()

	def GreenPressed(self):
		backup = None
		self.BackupRunning = False
		for job in Components.Task.job_manager.getPendingJobs():
			if job.name.startswith(_("Image Manager")):
				backup = job
				self.BackupRunning = True
		if self.BackupRunning and backup:
			self.showJobView(backup)
		else:
			self.keyBackup()

	def keyBackup(self):
		if getBoxType().startswith('vu') or getBoxType().startswith('et') or getBoxType().startswith('tm') or getBoxType().startswith('odin') or getBoxType().startswith('venton') or getBoxType().startswith('ini') or getBoxType().startswith('gb') or getBoxType().startswith('xp') or getBoxType().startswith('iqon'):
			message = _("Are you ready to create a backup image ?")
			ybox = self.session.openWithCallback(self.doBackup, MessageBox, message, MessageBox.TYPE_YESNO)
			ybox.setTitle(_("Backup Confirmation"))
		else:
			self.session.open(MessageBox, _("Sorry you %s %s is not yet compatible."), MessageBox.TYPE_INFO, timeout = 10) % (getMachineBrand(), getMachineName())

	def doBackup(self,answer):
		backup = None
		if answer is True:
			self.ImageBackup = ImageBackup(self.session)
			Components.Task.job_manager.AddJob(self.ImageBackup.createBackupJob())
			self.BackupRunning = True
			self["key_green"].setText(_("View Progress"))
			self["key_green"].show()
			for job in Components.Task.job_manager.getPendingJobs():
				if job.name.startswith(_("Image Manager")):
					backup = job
			if backup:
				self.showJobView(backup)

	def keyResstore(self):
		self.sel = self['list'].getCurrent()
		if self.sel:
			message = _("Are you sure you want to restore this image:\n ") + self.sel
			ybox = self.session.openWithCallback(self.keyResstore2, MessageBox, message, MessageBox.TYPE_YESNO)
			ybox.setTitle(_("Restore Confirmation"))
		else:
			self.session.open(MessageBox, _("You have no image to restore."), MessageBox.TYPE_INFO, timeout = 10)

	def keyResstore2(self, answer):
		if answer:
			self.session.open(MessageBox, _("Please wait while restore prepares"), MessageBox.TYPE_INFO, timeout = 60, enable_input=False)
			self.MAINDESTROOT = '/tmp/imagerestore'
			self.TEMPDESTROOT = self.BackupDirectory + 'imagerestore'
			if self.sel.endswith('.zip'):
				if not path.exists(self.TEMPDESTROOT):
					mkdir(self.TEMPDESTROOT, 0755)
				self.UnZipConsole = Console()
				self.UnZipConsole.ePopen('unzip -o ' + self.BackupDirectory + self.sel + ' -d ' + self.TEMPDESTROOT, self.keyResstore3)
				symlink(self.TEMPDESTROOT, '/tmp/imagerestore')
			else:
				symlink(self.BackupDirectory + self.sel, '/tmp/imagerestore')
				self.keyResstore3(0,0)

	def keyResstore3(self, result, retval, extra_args = None):
		print 'result:',result
		if retval == 0:
			self.MAINDEST = None
			self.kernelMTD = None
			self.kernelFILE = None
			self.rootMTD = None
			self.rootFILE = None
			if getBoxType().startswith('vu'):
				self.MAINDEST = self.MAINDESTROOT + '/vuplus/' + getBoxType().replace('vu','') + '/'
			elif getBoxType() == 'tmtwin':
				self.MAINDEST = self.MAINDESTROOT + '/update/tmtwinoe/cfe/'
			elif getBoxType() == 'tm2t':
				self.MAINDEST = self.MAINDESTROOT + '/update/tm2toe/cfe/'
			elif getBoxType() == 'tmsingle':
				self.MAINDEST = self.MAINDESTROOT + '/update/tmsingle/cfe/'
			elif getBoxType() == 'tmnano':
				self.MAINDEST = self.MAINDESTROOT + '/update/tmnano/cfe'
			elif getBoxType() == 'tmnano2t':
				self.MAINDEST = self.MAINDESTROOT + '/update/tmnano2t/cfe'
			elif getBoxType() == 'iqonios100hd':
				self.MAINDEST = self.MAINDESTROOT + '/update/ios100/cfe/'
			elif getBoxType() == 'iqoniso200hd':
				self.MAINDEST = self.MAINDESTROOT + '/update/ios200/cfe/'
			elif getBoxType() == 'iqoniso300hd':
				self.MAINDEST = self.MAINDESTROOT + '/update/ios300/cfe/'
			elif getBoxType() == 'gb800solo':
				self.MAINDEST = self.MAINDESTROOT + '/gigablue/solo/'
			elif getBoxType() == 'gb800se':
				self.MAINDEST = self.MAINDESTROOT + '/gigablue/se/'
			elif getBoxType() == 'gb800ue':
				self.MAINDEST = self.MAINDESTROOT + '/gigablue/ue/'
			elif getBoxType() == 'gb800seplus':
				self.MAINDEST = self.MAINDESTROOT + '/gigablue/seplus/'
			elif getBoxType() == 'gb800ueplus':
				self.MAINDEST = self.MAINDESTROOT + '/gigablue/ueplus/'
			elif getBoxType() == 'gbquad':
				self.MAINDEST = self.MAINDESTROOT + '/gigablue/quad/'
			elif getBoxType().startswith('ventonhdx'):
				self.MAINDEST = self.MAINDESTROOT + '/venton-hdx/'
			elif getBoxType().startswith('ini'):
				self.MAINDEST = self.MAINDESTROOT + '/' + getBoxType().replace('ini','') + '/'
			else:
				self.MAINDEST = self.MAINDESTROOT + '/' + getBoxType() + '/'

			if getBoxType().startswith('gb'):
				self.kernelMTD = "mtd2"
				self.kernelFILE = "kernel.bin"
				self.rootMTD = "mtd0"
				self.rootFILE = "rootfs.bin"
			elif getBoxType().startswith('et') or getBoxType().startswith('venton') or getBoxType().startswith('ini') or getBoxType().startswith('xp'):
				self.kernelMTD = "mtd1"
				self.kernelFILE = "kernel.bin"
				self.rootMTD = "mtd2"
				self.rootFILE = "rootfs.bin"
			elif getBoxType().startswith('odin'):
				self.kernelMTD = "mtd2"
				self.kernelFILE = "kernel.bin"
				self.rootMTD = "mtd3"
				self.rootFILE = "rootfs.bin"
			elif getBoxType() == 'tmnano' or getBoxType() == 'tmnano2t':
				self.kernelMTD = "mtd1"
				self.kernelFILE = "oe_kernel.bin"
				self.rootMTD = "mtd0"
				self.rootFILE = "oe_rootfs.bin"
			elif getBoxType().startswith('tm') or getBoxType().startswith('iqon'):
				self.kernelMTD = "mtd6"
				self.kernelFILE = "oe_kernel.bin"
				self.rootMTD = "mtd4"
				self.rootFILE = "oe_rootfs.bin"
			elif getBoxType() == 'vusolo' or getBoxType() == 'vuduo' or getBoxType() == 'vuuno' or getBoxType() == 'vuultimo':
				self.kernelMTD = "mtd1"
				self.kernelFILE = "kernel_cfe_auto.bin"
				self.rootMTD = "mtd0"
				self.rootFILE = "root_cfe_auto.jffs2"
			elif getBoxType() == 'vusolo2' or getBoxType() == 'vuduo2':
				self.kernelMTD = "mtd2"
				self.kernelFILE = "kernel_cfe_auto.bin"
				self.rootMTD = "mtd0"
				self.rootFILE = "root_cfe_auto.bin"

			if self.kernelMTD:
				self.doRestore()
			else:
				rmtree(self.TEMPDESTROOT)
				self.session.open(MessageBox, _("Sorry Image Restore is not supported on the" + ' ' + getBoxType() + ', ' + _("Please copy the folder") + ' ' + self.BackupDirectory + self.sel +  ' \n' + _("to a USB stick, place in front USB port of reciver and power on")), MessageBox.TYPE_INFO, timeout = 30)

	def doRestore(self):
		print 'doRestore'
		config.imagemanager.restoreimage.value = self.sel
		f = open('/proc/mounts')
		filesystem = f.read()
		f.close()

		mkdir('/tmp/apps', 0755)
		apps = '/tmp/apps/'
		copy('/usr/sbin/nandwrite',apps)
		copy('/usr/sbin/flash_erase',apps)
		copy('/usr/sbin/ubiformat',apps)
		copy('/sbin/reboot',apps)
		copy('/bin/sleep',apps)
		copy('/bin/rm',apps)

		output = open('/tmp/image_restore.sh','w')
		command = []
		header = '#!/bin/sh\n'
		sleep = apps + 'sleep 3 && '

		command.append(header)
		command.append('sync && ')
		command.append(sleep)

		command.append('if [ "$(pidof smbd)" ]; then killall smbd ; fi && ')
		command.append('if [ "$(pidof nmbd)" ]; then killall nmbd ; fi && ')
		command.append('if [ "$(pidof rpc.mountd)" ]; then killall rpc.mountd ; fi && ')
		command.append('if [ "$(pidof rpc.statd)" ]; then killall rpc.statd ; fi && ')

		command.append('mount -no remount,ro / && ')
		command.append(apps + 'flash_erase /dev/' + self.kernelMTD + ' 0 0 && ')
		command.append(apps + 'nandwrite -pm /dev/' + self.kernelMTD + ' ' + self.MAINDEST + self.kernelFILE + ' && ')
		if filesystem.find('ubifs') != -1:
			command.append(apps + 'ubiformat /dev/' + self.rootMTD + ' -f ' + self.MAINDEST + self.rootFILE + ' -D && ')
		else:
			command.append(apps + 'nandwrite -pm /dev/' + self.rootMTD + ' -f ' + self.MAINDEST + self.rootFILE + ' -D && ')
		command.append(sleep)
		command.append(apps + 'reboot -fn')

		commandline = ''.join(command)

		output.write(commandline)
		output.close()
		chmod('/tmp/image_restore.sh', 0755)
		self.session.open(TryQuitMainloop,retvalue=43)
		self.close()

class AutoImageManagerTimer:
	def __init__(self, session):
		self.session = session
		self.backuptimer = eTimer()
		self.backuptimer.callback.append(self.BackuponTimer)
		self.backupactivityTimer = eTimer()
		self.backupactivityTimer.timeout.get().append(self.backupupdatedelay)
		now = int(time())
		global BackupTime
		if config.imagemanager.schedule.value:
			print "[ImageManager] Backup Schedule Enabled at ", strftime("%c", localtime(now))
			if now > 1262304000:
				self.backupupdate()
			else:
				print "[ImageManager] Backup Time not yet set."
				BackupTime = 0
				self.backupactivityTimer.start(36000)
		else:
			BackupTime = 0
			print "[ImageManager] Backup Schedule Disabled at", strftime("(now=%c)", localtime(now))
			self.backupactivityTimer.stop()

	def backupupdatedelay(self):
		self.backupactivityTimer.stop()
		self.backupupdate()

	def getBackupTime(self):
		backupclock = config.imagemanager.scheduletime.value
		nowt = time()
		now = localtime(nowt)
		return int(mktime((now.tm_year, now.tm_mon, now.tm_mday, backupclock[0], backupclock[1], 0, now.tm_wday, now.tm_yday, now.tm_isdst)))

	def backupupdate(self, atLeast = 0):
		self.backuptimer.stop()
		global BackupTime
		BackupTime = self.getBackupTime()
		now = int(time())
		if BackupTime > 0:
			if BackupTime < now + atLeast:
				if config.imagemanager.repeattype.value == "daily":
					BackupTime += 24*3600
					while (int(BackupTime)-30) < now:
						BackupTime += 24*3600
				elif config.imagemanager.repeattype.value == "weekly":
					BackupTime += 7*24*3600
					while (int(BackupTime)-30) < now:
						BackupTime += 7*24*3600
				elif config.imagemanager.repeattype.value == "monthly":
					BackupTime += 30*24*3600
					while (int(BackupTime)-30) < now:
						BackupTime += 30*24*3600
			next = BackupTime - now
			self.backuptimer.startLongTimer(next)
		else:
			BackupTime = -1
		print "[ImageManager] Backup Time set to", strftime("%c", localtime(BackupTime)), strftime("(now=%c)", localtime(now))
		return BackupTime

	def backupstop(self):
		self.backuptimer.stop()

	def BackuponTimer(self):
		self.backuptimer.stop()
		now = int(time())
		wake = self.getBackupTime()
		# If we're close enough, we're okay...
		atLeast = 0
		if wake - now < 60:
			print "[ImageManager] Backup onTimer occured at", strftime("%c", localtime(now))
			from Screens.Standby import inStandby
			if not inStandby:
				message = _("Your %s %s is about to run a full image backup, this can take about 6 minutes to complete,\ndo you want to allow this?") % (getMachineBrand(), getMachineName())
				ybox = self.session.openWithCallback(self.doBackup, MessageBox, message, MessageBox.TYPE_YESNO, timeout = 30)
				ybox.setTitle('Scheduled Backup.')
			else:
				print "[ImageManager] in Standby, so just running backup", strftime("%c", localtime(now))
				self.doBackup(True)
		else:
			print '[ImageManager] Where are not close enough', strftime("%c", localtime(now))
			self.backupupdate(60)

	def doBackup(self, answer):
		now = int(time())
		if answer is False:
			if config.imagemanager.backupretrycount.value < 2:
				print '[ImageManager] Number of retries',config.imagemanager.backupretrycount.value
				print "[ImageManager] Backup delayed."
				repeat = config.imagemanager.backupretrycount.value
				repeat += 1
				config.imagemanager.backupretrycount.value = repeat
				BackupTime = now + (int(config.imagemanager.backupretry.value) * 60)
				print "[ImageManager] Backup Time now set to", strftime("%c", localtime(BackupTime)), strftime("(now=%c)", localtime(now))
				self.backuptimer.startLongTimer(int(config.imagemanager.backupretry.value) * 60)
			else:
				atLeast = 60
				print "[ImageManager] Enough Retries, delaying till next schedule.", strftime("%c", localtime(now))
				self.session.open(MessageBox, _("Enough Retries, delaying till next schedule."), MessageBox.TYPE_INFO, timeout = 10)
				config.imagemanager.backupretrycount.value = 0
				self.backupupdate(atLeast)
		else:
			print "[ImageManager] Running Backup", strftime("%c", localtime(now))
			self.ImageBackup = ImageBackup(self.session)
			Components.Task.job_manager.AddJob(self.ImageBackup.createBackupJob())
			#self.close()

class ImageBackup(Screen):
	def __init__(self, session, updatebackup=False):
		Screen.__init__(self, session)
		self.updatebackup = updatebackup
		self.swapdevice = ""
		self.RamChecked = False
		self.SwapCreated = False
		self.Stage1Completed = False
		self.Stage2Completed = False
		self.Stage3Completed = False
		self.Stage4Completed = False
		self.Stage5Completed = False

	def createBackupJob(self):
		job = Components.Task.Job(_("Image Manager"))

		task = Components.Task.PythonTask(job, _("Setting Up..."))
		task.work = self.JobStart
		task.weighting = 5

		task = Components.Task.ConditionTask(job, _("Checking Free RAM.."), timeoutCount=10)
		task.check = lambda: self.RamChecked
		task.weighting = 5

		task = Components.Task.ConditionTask(job, _("Creating Swap.."), timeoutCount=120)
		task.check = lambda: self.SwapCreated
		task.weighting = 5

		task = Components.Task.PythonTask(job, _("Creating Backup Files..."))
		task.work = self.doBackup1
		task.weighting = 5

		task = Components.Task.ConditionTask(job, _("Creating Backup Files..."), timeoutCount=900)
		task.check = lambda: self.Stage1Completed
		task.weighting = 35

		task = Components.Task.PythonTask(job, _("Creating Backup Files..."))
		task.work = self.doBackup2
		task.weighting = 5

		task = Components.Task.ConditionTask(job, _("Creating Backup Files..."), timeoutCount=900)
		task.check = lambda: self.Stage2Completed
		task.weighting = 15

		task = Components.Task.PythonTask(job, _("Removing temp mounts..."))
		task.work = self.doBackup3
		task.weighting = 5

		task = Components.Task.ConditionTask(job, _("Removing temp mounts..."), timeoutCount=900)
		task.check = lambda: self.Stage3Completed
		task.weighting = 5

		task = Components.Task.PythonTask(job, _("Moving to Backup Location..."))
		task.work = self.doBackup4
		task.weighting = 5

		task = Components.Task.ConditionTask(job, _("Moving to Backup Location..."), timeoutCount=900)
		task.check = lambda: self.Stage4Completed
		task.weighting = 5

		task = Components.Task.PythonTask(job, _("Creating zip..."))
		task.work = self.doBackup5
		task.weighting = 5

		task = Components.Task.ConditionTask(job, _("Creating zip..."), timeoutCount=900)
		task.check = lambda: self.Stage5Completed
		task.weighting = 5

		task = Components.Task.PythonTask(job, _("Backup Complete..."))
		task.work = self.BackupComplete
		task.weighting = 5

		return job

	def JobStart(self):
		imparts = []
		for p in harddiskmanager.getMountedPartitions():
			if path.exists(p.mountpoint):
				d = path.normpath(p.mountpoint)
				if p.mountpoint != '/':
					imparts.append((p.mountpoint, d))

		config.imagemanager.backuplocation.setChoices(imparts)

		if config.imagemanager.backuplocation.value.endswith('/'):
			mount = config.imagemanager.backuplocation.value, config.imagemanager.backuplocation.value[:-1]
		else:
			mount = config.imagemanager.backuplocation.value+'/', config.imagemanager.backuplocation.value
		hdd = '/media/hdd/','/media/hdd'
		if mount not in config.imagemanager.backuplocation.choices.choices:
			if hdd in config.imagemanager.backuplocation.choices.choices:
				config.imagemanager.backuplocation.value = '/media/hdd/'
				config.imagemanager.backuplocation.save()
				self.BackupDevice = config.imagemanager.backuplocation.value
				print "[ImageManager] Device: " + self.BackupDevice
				self.BackupDirectory = config.imagemanager.backuplocation.value + 'imagebackups/'
				print "[ImageManager] Directory: " + self.BackupDirectory
				print "The chosen location does not exist, using /media/hdd"
			else:
				print "Device: None available"
		else:
			self.BackupDevice = config.imagemanager.backuplocation.value
			print "[ImageManager] Device: " + self.BackupDevice
			self.BackupDirectory = config.imagemanager.backuplocation.value + 'imagebackups/'
			print "[ImageManager] Directory: " + self.BackupDirectory

		try:
			if not path.exists(self.BackupDirectory):
				mkdir(self.BackupDirectory, 0755)
			if path.exists(self.BackupDirectory + config.imagemanager.folderprefix.value + "-swapfile_backup"):
				system('swapoff ' + self.BackupDirectory + config.imagemanager.folderprefix.value + "-swapfile_backup")
				remove(self.BackupDirectory + config.imagemanager.folderprefix.value + "-swapfile_backup")
		except Exception,e:
			print str(e)
			print "Device: " + config.imagemanager.backuplocation.value + ", i don't seem to have write access to this device."

		s = statvfs(self.BackupDevice)
		free = (s.f_bsize * s.f_bavail)/(1024*1024)
		if int(free) < 200:
			AddPopupWithCallback(self.BackupComplete,
				_("The backup location does not have enough freespace." + "\n" + self.BackupDevice + "only has " + str(free) + "MB free."),
				MessageBox.TYPE_INFO,
				10,
				'RamCheckFailedNotification'
			)
		else:
			self.MemCheck()

	def MemCheck(self):
		memfree = 0
		swapfree = 0
		f = open('/proc/meminfo', 'r')
		for line in f.readlines():
			if line.find('MemFree') != -1:
				parts = line.strip().split()
				memfree = int(parts[1])
			elif line.find('SwapFree') != -1:
				parts = line.strip().split()
				swapfree = int(parts[1])
		f.close()
		TotalFree = memfree + swapfree
		print '[ImageManager] Stage1: Free Mem',TotalFree
		if int(TotalFree) < 3000:
			self.MemCheckConsole = Console()
			supported_filesystems = frozenset(('ext4', 'ext3', 'ext2'))
			candidates = []
			mounts = getProcMounts()
			for partition in harddiskmanager.getMountedPartitions(False, mounts):
				if partition.filesystem(mounts) in supported_filesystems:
					candidates.append((partition.description, partition.mountpoint))
			for swapdevice in candidates:
				self.swapdevice = swapdevice[1]
			if self.swapdevice:
				print '[ImageManager] Stage1: Creating Swapfile.'
				self.RamChecked = True
				self.MemCheck2()
			else:
				print '[ImageManager] Sorry, not enough free ram found, and no physical devices that supports SWAP attached'
				AddPopupWithCallback(self.BackupComplete,
					_("Sorry, not enough free ram found, and no physical devices that supports SWAP attached. Can't create Swapfile on network or fat32 filesystems, unable to make backup"),
					MessageBox.TYPE_INFO,
					10,
					'RamCheckFailedNotification'
				)
		else:
			print '[ImageManager] Stage1: Found Enough Ram'
			self.RamChecked = True
			self.SwapCreated = True

	def MemCheck2(self):
		self.MemCheckConsole.ePopen("dd if=/dev/zero of=" + self.swapdevice + config.imagemanager.folderprefix.value + "-swapfile_backup bs=1024 count=61440", self.MemCheck3)

	def MemCheck3(self, result, retval, extra_args = None):
		if retval == 0:
			self.MemCheckConsole = Console()
			self.MemCheckConsole.ePopen("mkswap " + self.swapdevice + config.imagemanager.folderprefix.value + "-swapfile_backup", self.MemCheck4)

	def MemCheck4(self, result, retval, extra_args = None):
		if retval == 0:
			self.MemCheckConsole = Console()
			self.MemCheckConsole.ePopen("swapon " + self.swapdevice + config.imagemanager.folderprefix.value + "-swapfile_backup", self.MemCheck5)

	def MemCheck5(self, result, retval, extra_args = None):
		self.SwapCreated = True

	def doBackup1(self):
		f = open('/proc/mounts')
		filesystem = f.read()
		f.close()
		if filesystem.find('ubifs') != -1:
			self.ROOTFSTYPE = 'ubifs'
		else:
			self.ROOTFSTYPE= 'jffs2'
		self.BackupConsole = Console()
		print '[ImageManager] Stage1: Creating tmp folders.',self.BackupDirectory
		self.BackupDate = getImageVersion() + '.' + getImageBuild() + '-' + strftime('%Y%m%d_%H%M%S', localtime())
		self.WORKDIR=self.BackupDirectory + config.imagemanager.folderprefix.value + '-temp'
		self.TMPDIR=self.BackupDirectory + config.imagemanager.folderprefix.value + '-mount'
		if self.updatebackup:
			self.MAINDESTROOT=self.BackupDirectory + config.imagemanager.folderprefix.value + '-SoftwareUpdate-' + self.BackupDate
		else:
			self.MAINDESTROOT=self.BackupDirectory + config.imagemanager.folderprefix.value + '-' + self.BackupDate
		MKFS='mkfs.' + self.ROOTFSTYPE
		if getBoxType() =='gb800solo':
			JFFS2OPTIONS=" --disable-compressor=lzo -e131072 -l -p125829120"
		else:
			JFFS2OPTIONS=" --disable-compressor=lzo --eraseblock=0x20000 -n -l"
		UBINIZE='ubinize'
		UBINIZE_ARGS="-m 2048 -p 128KiB"
		print '[ImageManager] Stage1: Creating backup Folders.'
		if path.exists(self.WORKDIR):
			rmtree(self.WORKDIR)
		mkdir(self.WORKDIR, 0644)
		if path.exists(self.TMPDIR + '/root') and path.ismount(self.TMPDIR + '/root'):
			system('umount ' + self.TMPDIR + '/root')
		elif path.exists(self.TMPDIR + '/root'):
			rmtree(self.TMPDIR + '/root')
		if path.exists(self.TMPDIR):
			rmtree(self.TMPDIR)
		makedirs(self.TMPDIR + '/root', 0644)
		makedirs(self.MAINDESTROOT, 0644)
		self.commands = []
		print '[ImageManager] Stage1: Making Root Image.'
		if getBoxType().startswith('vu'):
			self.MAINDEST = self.MAINDESTROOT + '/vuplus/' + getBoxType().replace('vu','')
		elif getBoxType() == 'tmtwin':
			self.MAINDEST = self.MAINDESTROOT + '/update/tmtwinoe/cfe'
		elif getBoxType() == 'tm2t':
			self.MAINDEST = self.MAINDESTROOT + '/update/tm2toe/cfe'
		elif getBoxType() == 'tmsingle':
			self.MAINDEST = self.MAINDESTROOT + '/update/tmsingle/cfe'
		elif getBoxType() == 'tmnano':
			self.MAINDEST = self.MAINDESTROOT + '/update/tmnano/cfe'
		elif getBoxType() == 'tmnano2t':
			self.MAINDEST = self.MAINDESTROOT + '/update/tmnano2t/cfe'
		elif getBoxType() == 'iqonios100hd':
			self.MAINDEST = self.MAINDESTROOT + '/update/ios100/cfe'
		elif getBoxType() == 'iqoniso200hd':
			self.MAINDEST = self.MAINDESTROOT + '/update/ios200/cfe'
		elif getBoxType() == 'iqoniso300hd':
			self.MAINDEST = self.MAINDESTROOT + '/update/ios300/cfe'
		elif getBoxType() == 'gb800solo':
			self.MAINDEST = self.MAINDESTROOT + '/gigablue/solo'
		elif getBoxType() == 'gb800se':
			self.MAINDEST = self.MAINDESTROOT + '/gigablue/se'
		elif getBoxType() == 'gb800ue':
			self.MAINDEST = self.MAINDESTROOT + '/gigablue/ue'
		elif getBoxType() == 'gb800seplus':
			self.MAINDEST = self.MAINDESTROOT + '/gigablue/seplus'
		elif getBoxType() == 'gb800ueplus':
			self.MAINDEST = self.MAINDESTROOT + '/gigablue/ueplus'
		elif getBoxType() == 'gbquad':
			self.MAINDEST = self.MAINDESTROOT + '/gigablue/quad'
		elif getBoxType().startswith('ventonhdx'):
			self.MAINDEST = self.MAINDESTROOT + '/venton-hdx/'
		elif getBoxType().startswith('ini'):
			self.MAINDEST = self.MAINDESTROOT + '/' + getBoxType().replace('ini','') + '/'
		else:
			self.MAINDEST = self.MAINDESTROOT + '/' + getBoxType()
		makedirs(self.MAINDEST, 0644)
		if self.ROOTFSTYPE == 'jffs2':
			print '[ImageManager] Stage1: JFFS2 Detected.'
			self.commands.append('mount --bind / ' + self.TMPDIR + '/root')
			self.commands.append(MKFS + ' --root=' + self.TMPDIR + '/root --faketime --output=' + self.WORKDIR + '/root.jffs2' + JFFS2OPTIONS)
		elif self.ROOTFSTYPE == 'ubifs':
			print '[ImageManager] Stage1: UBIFS Detected.'
			MKUBIFS_ARGS = ""
			if getBoxType().startswith('vu'):
				MKUBIFS_ARGS="-m 2048 -e 126976 -c 4096 -F"
			elif getBoxType().startswith('tm') or getBoxType().startswith('iqon'):
				MKUBIFS_ARGS="-m 2048 -e 126976 -c 4096 -F"
			elif getBoxType().startswith('gb'):
				MKUBIFS_ARGS="-m 2048 -e 126976 -c 4096"
			elif getBoxType().startswith('et') or getBoxType().startswith('odin') or getBoxType().startswith('xp'):
				MKUBIFS_ARGS="-m 2048 -e 126976 -c 4096"
			elif getBoxType().startswith('venton') or getBoxType().startswith('ini'):
				MKUBIFS_ARGS="-m 2048 -e 126976 -c 4096"
			output = open(self.WORKDIR + '/ubinize.cfg','w')
			output.write('[ubifs]\n')
			output.write('mode=ubi\n')
			output.write('image=' + self.WORKDIR + '/root.ubi\n')
			output.write('vol_id=0\n')
			output.write('vol_type=dynamic\n')
			output.write('vol_name=rootfs\n')
			output.write('vol_flags=autoresize\n')
			output.close()
			self.commands.append('mount --bind / ' + self.TMPDIR + '/root')
			self.commands.append('touch ' + self.WORKDIR + '/root.ubi')
			self.commands.append(MKFS + ' -r ' + self.TMPDIR + '/root -o ' + self.WORKDIR + '/root.ubi ' + MKUBIFS_ARGS)
			self.commands.append('ubinize -o ' + self.WORKDIR + '/root.ubifs ' + UBINIZE_ARGS + ' ' + self.WORKDIR + '/ubinize.cfg')
		self.BackupConsole.eBatch(self.commands, self.Stage1Complete, debug=False)

	def Stage1Complete(self, extra_args = None):
		if len(self.BackupConsole.appContainers) == 0:
			self.Stage1Completed = True
			print '[ImageManager] Stage1: Complete.'

	def doBackup2(self):
		print '[ImageManager] Stage2: Making Kernel Image.'
		if getBoxType().startswith('et') or getBoxType().startswith('venton') or getBoxType().startswith('ini') or getBoxType().startswith('xp') or getBoxType() == 'vusolo' or getBoxType() == 'vuduo' or getBoxType() == 'vuuno' or getBoxType() == 'vuultimo' or getBoxType() == 'tmnano' or getBoxType() == 'tmnano2t':
			self.command = 'nanddump /dev/mtd1 -f ' + self.WORKDIR + '/vmlinux.gz'
		elif getBoxType().startswith('odin') or getBoxType().startswith('gb') or getBoxType() == 'vusolo2' or getBoxType() == 'vuduo2':
			self.command = 'nanddump /dev/mtd2 -f ' + self.WORKDIR + '/vmlinux.gz'
		elif getBoxType().startswith('tm') or getBoxType().startswith('iqon'):
			self.command = 'nanddump /dev/mtd6 -f ' + self.WORKDIR + '/vmlinux.gz'
		self.BackupConsole.ePopen(self.command, self.Stage2Complete)

	def Stage2Complete(self, result, retval, extra_args = None):
		if retval == 0:
			self.Stage2Completed = True
			print '[ImageManager] Stage2: Complete.'

	def doBackup3(self):
		print '[ImageManager] Stage3: Unmounting and removing tmp system'
		if path.exists(self.TMPDIR + '/root'):
			self.command = 'umount ' + self.TMPDIR + '/root && rm -rf ' + self.TMPDIR
			self.BackupConsole.ePopen(self.command, self.Stage3Complete)

	def Stage3Complete(self, result, retval, extra_args = None):
		if retval == 0:
			self.Stage3Completed = True
			print '[ImageManager] Stage3: Complete.'

	def doBackup4(self):
		imagecreated = False
		print '[ImageManager] Stage4: Moving from work to backup folders'
		if getBoxType() == 'vusolo' or getBoxType() == 'vuduo' or getBoxType() == 'vuuno' or getBoxType() == 'vuultimo':
			move(self.WORKDIR + '/root.' + self.ROOTFSTYPE, self.MAINDEST + '/root_cfe_auto.jffs2')
			move(self.WORKDIR + '/vmlinux.gz', self.MAINDEST + '/kernel_cfe_auto.bin')
			fileout = open(self.MAINDEST + '/reboot.update', 'w')
			line = "This file forces a reboot after the update."
			fileout.write(line)
			fileout.close()
			fileout = open(self.MAINDEST + '/imageversion', 'w')
			line = "openvix-" + self.BackupDate
			fileout.write(line)
			fileout.close()
			imagecreated = True
		elif getBoxType() == 'vusolo2' or getBoxType() == 'vuduo2':
			move(self.WORKDIR + '/root.' + self.ROOTFSTYPE, self.MAINDEST + '/root_cfe_auto.bin')
			move(self.WORKDIR + '/vmlinux.gz', self.MAINDEST + '/kernel_cfe_auto.bin')
			fileout = open(self.MAINDEST + '/reboot.update', 'w')
			line = "This file forces a reboot after the update."
			fileout.write(line)
			fileout.close()
			fileout = open(self.MAINDEST + '/imageversion', 'w')
			line = "openvix-" + self.BackupDate
			fileout.write(line)
			fileout.close()
			imagecreated = True
		elif getBoxType().startswith('et') or getBoxType().startswith('odin') or getBoxType().startswith('venton') or getBoxType().startswith('ini') or getBoxType().startswith('gb') or getBoxType().startswith('xp'):
			move(self.WORKDIR + '/root.' + self.ROOTFSTYPE, self.MAINDEST + '/rootfs.bin')
			move(self.WORKDIR + '/vmlinux.gz', self.MAINDEST + '/kernel.bin')
			if getBoxType().startswith('et') or getBoxType().startswith('odin'):
				fileout = open(self.MAINDEST + '/noforce', 'w')
				line = "rename this file to 'force' to force an update without confirmation"
				fileout.write(line)
				fileout.close()
				fileout = open(self.MAINDEST + '/imageversion', 'w')
				line = "openvix-" + self.BackupDate
				fileout.write(line)
				fileout.close()
			if getBoxType() == 'gb800solo' or getBoxType() == 'gb800se':
				copy('/usr/lib/enigma2/python/Plugins/SystemPlugins/ViX/burn.bat', self.MAINDESTROOT + '/burn.bat')
			imagecreated = True
		elif getBoxType().startswith('tm') or getBoxType().startswith('iqon'):
			move(self.WORKDIR + '/root.' + self.ROOTFSTYPE, self.MAINDEST + '/oe_rootfs.bin')
			move(self.WORKDIR + '/vmlinux.gz', self.MAINDEST + '/oe_kernel.bin')
			imagecreated = True
		print '[ImageManager] Stage4: Removing Swap.'
		if path.exists(self.swapdevice + config.imagemanager.folderprefix.value + "-swapfile_backup"):
			system('swapoff ' + self.swapdevice + config.imagemanager.folderprefix.value + "-swapfile_backup")
			remove(self.swapdevice + config.imagemanager.folderprefix.value + "-swapfile_backup")
		if path.exists(self.WORKDIR):
			rmtree(self.WORKDIR)
		if imagecreated:
			for root, dirs, files in walk(self.MAINDEST):
				for momo in dirs:
					chmod(path.join(root, momo), 0644)
				for momo in files:
					chmod(path.join(root, momo), 0644)
			print '[ImageManager] Stage4: Image created in ' + self.MAINDESTROOT
			self.Stage4Complete()
		else:
			print "[ImageManager] Stage4: Image creation failed - e. g. wrong backup destination or no space left on backup device"
			self.BackupComplete()

	def Stage4Complete(self):
		self.Stage4Completed = True
		print '[ImageManager] Stage4: Complete.'

	def doBackup5(self):
		zipfolder = path.split(self.MAINDESTROOT)
		self.commands = []
		self.commands.append('cd ' + self.MAINDESTROOT +' && zip -r ' + self.MAINDESTROOT + '.zip *')
		self.commands.append('rm -rf ' + self.MAINDESTROOT)
		self.BackupConsole.eBatch(self.commands, self.Stage5Complete, debug=True)

	def Stage5Complete(self, anwser=None):
		self.Stage5Completed = True
		print '[ImageManager] Stage5: Complete.'

	def BackupComplete(self, anwser=None):
		if config.imagemanager.schedule.value:
			atLeast = 60
			autoImageManagerTimer.backupupdate(atLeast)
		else:
			autoImageManagerTimer.backupstop()

class ImageManagerDownload(Screen):
	def __init__(self, session, BackupDirectory):
		Screen.__init__(self, session)
		Screen.setTitle(self, _("Image Manager"))
		self.BackupDirectory = BackupDirectory
		self['lab1'] = Label(_("Select an image to Download:"))
		self["key_red"] = Button(_("Close"))
		self["key_green"] = Button(_("Download"))

		self.onChangedEntry = [ ]
		self.emlist = []
		self['list'] = MenuList(self.emlist)
		self.populate_List()

		if not self.selectionChanged in self["list"].onSelectionChanged:
			self["list"].onSelectionChanged.append(self.selectionChanged)

	def selectionChanged(self):
		for x in self.onChangedEntry:
			x()

	def populate_List(self):
		try:
			self['myactions'] = ActionMap(['ColorActions', 'OkCancelActions', 'DirectionActions'],
				{
					'cancel': self.close,
					'red': self.close,
					'green': self.keyDownload,
					'ok': self.keyDownload,
				}, -1)

			if not path.exists(self.BackupDirectory):
				mkdir(self.BackupDirectory, 0755)
			from ftplib import FTP
			import urllib, zipfile, base64
			wos_user = 'vixlogs@world-of-satellite.com'
			wos_pwd = base64.b64decode('cDRsWF4sTHRGNkI4Cg==').replace('\n','')
			ftp = FTP('world-of-satellite.com')
			ftp.login(wos_user,wos_pwd)
			if getBoxType() == 'vuuno':
				self.boxtype = 'Vu+Uno'
			elif getBoxType() == 'vuultimo':
				self.boxtype = 'Vu+Ultimo'
			elif getBoxType() == 'vusolo':
				self.boxtype = 'Vu+Solo'
			elif getBoxType() == 'vusolo2':
				self.boxtype = 'Vu+Solo2'
			elif getBoxType() == 'vuduo':
				self.boxtype = 'Vu+Duo'
			elif getBoxType() == 'vuduo2':
				self.boxtype = 'Vu+Duo2'
			elif getBoxType() == 'et4x00':
				self.boxtype = 'ET-4x00'
			elif getBoxType() == 'et5x00':
				self.boxtype = 'ET-5x00'
			elif getBoxType() == 'et6x00':
				self.boxtype = 'ET-6x00'
			elif getBoxType() == 'et9x00':
				self.boxtype = 'ET-9x00'
			elif getBoxType() == 'tmtwin':
				self.boxtype = 'TM-Twin-OE'
			elif getBoxType() == 'tm2t':
				self.boxtype = 'TM-2T'
			elif getBoxType() == 'tmsingle':
				self.boxtype = 'TM-Single'
			elif getBoxType() == 'tmnano':
				self.boxtype = 'TM-Nano-OE'
			elif getBoxType() == 'tmnano2t':
				self.boxtype = 'TM-Nano-2T'
			elif getBoxType() == 'iqonios100hd':
				self.boxtype = 'iqon-IOS-100HD'
			elif getBoxType() == 'iqonios200hd':
				self.boxtype = 'iqon-IOS-200HD'
			elif getBoxType() == 'iqonios300hd':
				self.boxtype = 'iqon-IOS-300HD'
			elif getBoxType() == 'odinm9':
				self.boxtype = 'Odin-M9'
			elif getBoxType() == 'xp1000':
				self.boxtype = 'OCTAGON-SF8-HD-XP1000'
			elif getBoxType() == 'qb800solo':
				self.boxtype = 'GiGaBlue-HD800Solo'
			elif getBoxType() == 'gb800se':
				self.boxtype = 'GiGaBlue-HD800SE'
			elif getBoxType() == 'gb800ue':
				self.boxtype = 'GiGaBlue-HD800UE'
			elif getBoxType() == 'gb800seplus':
				self.boxtype = 'GiGaBlue-HD800SE-PLUS'
			elif getBoxType() == 'gb800ueplus':
				self.boxtype = 'GiGaBlue-HD800UE-PLUS'
			elif getBoxType() == 'gbquad':
				self.boxtype = 'GiGaBlue-HD-QUAD'
			elif getBoxType() == 'ventonhdx':
				self.boxtype = 'Venton-Unibox-HDx'
			elif getBoxType() == 'inihde':
				self.boxtype = 'INI-HDe'
			ftp.cwd(self.boxtype)

			del self.emlist[:]
			for fil in ftp.nlst():
				if not fil.endswith('.') and fil.find(getBoxType()) != -1:
					self.emlist.append(fil)
			self.emlist.sort()
			self.emlist.reverse()
			ftp.quit()
			ftp.close()
		except:
			self['myactions'] = ActionMap(['ColorActions', 'OkCancelActions', 'DirectionActions'],
				{
					'cancel': self.close,
					'red': self.close,
				}, -1)
			self.emlist.append(" ")
		self["list"].setList(self.emlist)
		self["list"].show()

	def keyDownload(self):
		self.sel = self['list'].getCurrent()
		if self.sel:
			message = _("Are you sure you want to download this image:\n ") + self.sel
			ybox = self.session.openWithCallback(self.doDownload, MessageBox, message, MessageBox.TYPE_YESNO)
			ybox.setTitle(_("Download Confirmation"))
		else:
			self.session.open(MessageBox, _("You have no image to download."), MessageBox.TYPE_INFO, timeout = 10)

	def doDownload(self,answer):
		if answer is True:
			self.selectedimage = self['list'].getCurrent()
			file = self.BackupDirectory + self.selectedimage
			from Screens.Console import Console as RestoreConsole
			mycmd1 = _("echo 'Downloading Image.'")
			mycmd2 = "wget -q http://enigma2.world-of-satellite.com//openvix/openvix-builds/" + self.boxtype + "/" + self.selectedimage + " -O " + self.BackupDirectory + "image.zip"
			mycmd3 = "mv " + self.BackupDirectory + "image.zip " + file
			self.session.open(RestoreConsole, title=_('Downloading Image...'), cmdlist=[mycmd1, mycmd2, mycmd3],closeOnSuccess = True)

	def myclose(self, result, retval, extra_args):
		remove(self.BackupDirectory + self.selectedimage)
		self.close()
