from urllib.request import urlopen

import json
import tempfile

from boxbranding import getImageType, getImageDistro, getImageVersion, getImageDevBuild, getImageFolder, getImageFileSystem, getMachineBuild, getMachineMtdRoot, getMachineRootFile, getMachineMtdKernel, getMachineKernelFile, getMachineMKUBIFS, getMachineUBINIZE
from enigma import eTimer, fbClass
from os import path, stat, system, mkdir, makedirs, listdir, remove, rename, rmdir, statvfs, chmod, walk
from shutil import rmtree, move, copy, copyfile
from time import localtime, time, strftime, mktime
from .__init__ import _, PluginLanguageDomain
from Components.ActionMap import ActionMap
from Components.Button import Button
from Components.ChoiceList import ChoiceList, ChoiceEntryComponent
from Components.config import config, ConfigSubsection, ConfigYesNo, ConfigSelection, ConfigText, ConfigNumber, NoSave, ConfigClock, configfile
from Components.Console import Console
from Components.Harddisk import harddiskmanager, getProcMounts, getFolderSize
from Components.Sources.StaticText import StaticText
from Components.Label import Label
from Components.MenuList import MenuList
from Components.SystemInfo import SystemInfo, BRAND, MODEL
import Components.Task
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.Setup import Setup
from Screens.Standby import TryQuitMainloop
from Screens.TaskView import JobView
from Tools.Directories import fileExists, pathExists, fileHas
import Tools.CopyFiles
from Tools.Multiboot import getImagelist, getCurrentImage
from Tools.Notifications import AddPopupWithCallback

kernelfile = getMachineKernelFile()
imagetype = getImageType()
imageversion = getImageVersion()
backupimage = "backupimage"
imagedistro = getImageDistro()
imagedir = getImageFolder()
imagefs = getImageFileSystem()

mountpointchoices = []
partitions = sorted(harddiskmanager.getMountedPartitions(), key=lambda partitions: partitions.device or "")
for parts in partitions:
	d = path.normpath(parts.mountpoint)
	if SystemInfo["canMultiBoot"]:
		if "mmcblk0p" in d or "mmcblk1p" in d:
			continue
	if parts.mountpoint != "/":
		mountpointchoices.append((parts.mountpoint, d))


def getMountDefault(mountpointchoices):
	mountpointchoices = {x[1]: x[0] for x in mountpointchoices}
	default = mountpointchoices.get(parts.mountpoint)
	return default


defaultprefix = imagedistro
config.imagemanager = ConfigSubsection()
config.imagemanager.autosettingsbackup = ConfigYesNo(default=True)
config.imagemanager.backuplocation = ConfigSelection(choices=mountpointchoices, default=getMountDefault(mountpointchoices))
config.imagemanager.backupretry = ConfigNumber(default=30)
config.imagemanager.backupretrycount = NoSave(ConfigNumber(default=0))
config.imagemanager.folderprefix = ConfigText(default=imagedistro, fixed_size=False)
config.imagemanager.nextscheduletime = NoSave(ConfigNumber(default=0))
config.imagemanager.repeattype = ConfigSelection(default="daily", choices=[("daily", _("Daily")), ("weekly", _("Weekly")), ("monthly", _("Monthly"))])
config.imagemanager.schedule = ConfigYesNo(default=False)
config.imagemanager.scheduletime = ConfigClock(default=0)  # 1:00
config.imagemanager.query = ConfigYesNo(default=True)
config.imagemanager.lastbackup = ConfigNumber(default=0)
config.imagemanager.number_to_keep = ConfigNumber(default=0)
config.imagemanager.imagefeed_OV = ConfigText(default="https://images.openvision.dedyn.io/json", fixed_size=False) if config.usage.alternative_imagefeed.value != "all" else ConfigText(default="https://images.openvision.dedyn.io/json%s" % config.usage.alternative_imagefeed.value, fixed_size=False)
config.imagemanager.imagefeed_OV.value = config.imagemanager.imagefeed_OV.default  # this is no longer a user setup option
config.imagemanager.imagefeed_ViX = ConfigText(default="https://www.openvix.co.uk/json", fixed_size=False)
config.imagemanager.imagefeed_ViX.value = config.imagemanager.imagefeed_ViX.default  # this is no longer a user setup option
config.imagemanager.imagefeed_ATV = ConfigText(default="http://images.mynonpublic.com/openatv/json", fixed_size=False)
config.imagemanager.imagefeed_ATV.value = config.imagemanager.imagefeed_ATV.default  # this is no longer a user setup option
config.imagemanager.imagefeed_PLi = ConfigText(default="http://downloads.openpli.org/json", fixed_size=False)
config.imagemanager.imagefeed_PLi.value = config.imagemanager.imagefeed_PLi.default  # this is no longer a user setup option
config.imagemanager.imagefeed_OBH = ConfigText(default="https://images.openbh.net/json", fixed_size=False)
config.imagemanager.imagefeed_OBH.value = config.imagemanager.imagefeed_OBH.default  # this is no longer a user setup option

autoImageManagerTimer = None

if path.exists(config.imagemanager.backuplocation.value + "/imagebackups/imagerestore"):
	try:
		rmtree(config.imagemanager.backuplocation.value + "/imagebackups/imagerestore")
	except Exception:
		pass
TMPMOUNTDIR = config.imagemanager.backuplocation.value + "/imagebackups/" + config.imagemanager.folderprefix.value + "-" + "mount"
if path.exists(TMPMOUNTDIR + "/root"):
	try:
		system("umount " + TMPMOUNTDIR + "/root")
	except Exception:
		pass


def ImageManagerautostart(reason, session=None, **kwargs):
	"""called with reason=1 to during /sbin/shutdown.sysvinit, with reason=0 at startup?"""
	global autoImageManagerTimer
	global _session
	now = int(time())
	if reason == 0:
		print("[ImageManager] AutoStart Enabled")
		if session is not None:
			_session = session
			if autoImageManagerTimer is None:
				autoImageManagerTimer = AutoImageManagerTimer(session)
	else:
		if autoImageManagerTimer is not None:
			print("[ImageManager] Stop")
			autoImageManagerTimer.stop()


class tmp:
	dir = None


class VISIONImageManager(Screen):
	skin = """<screen name="VISIONImageManager" position="center,center" size="560,400">
		<ePixmap pixmap="buttons/red.png" position="0,0" size="140,40" alphaTest="blend"/>
		<ePixmap pixmap="buttons/green.png" position="140,0" size="140,40" alphaTest="blend"/>
		<ePixmap pixmap="buttons/yellow.png" position="280,0" size="140,40" alphaTest="blend"/>
		<ePixmap pixmap="buttons/blue.png" position="420,0" size="140,40" alphaTest="blend"/>
		<widget name="key_red" position="0,0" zPosition="1" size="140,40" font="Regular;20" horizontalAlignment="center" verticalAlignment="center" backgroundColor="#9f1313" transparent="1"/>
		<widget name="key_green" position="140,0" zPosition="1" size="140,40" font="Regular;20" horizontalAlignment="center" verticalAlignment="center" backgroundColor="#1f771f" transparent="1"/>
		<widget name="key_yellow" position="280,0" zPosition="1" size="140,40" font="Regular;20" horizontalAlignment="center" verticalAlignment="center" backgroundColor="#a08500" transparent="1"/>
		<widget name="key_blue" position="420,0" zPosition="1" size="140,40" font="Regular;20" horizontalAlignment="center" verticalAlignment="center" backgroundColor="#18188b" transparent="1"/>
		<ePixmap pixmap="buttons/key_menu.png" position="0,40" size="35,25" alphaTest="blend" transparent="1" zPosition="3"/>
		<widget name="lab6" position="0,50" size="560,50" font="Regular; 18" zPosition="2" transparent="0" horizontalAlignment="center"/>
		<widget name="list" position="10,105" size="540,260" scrollbarMode="showOnDemand"/>
		<widget name="backupstatus" position="10,370" size="400,30" font="Regular;20" zPosition="5"/>
		<applet type="onLayoutFinish">
			self["list"].instance.setItemHeight(25)
		</applet>
	</screen>"""

	def __init__(self, session):
		Screen.__init__(self, session)
		self.setTitle(_("Vision Image Manager"))
		self["lab6"] = Label()
		self["backupstatus"] = Label()
		self["key_red"] = StaticText("")
		self["key_green"] = StaticText("")
		self["key_yellow"] = StaticText("")
		self["key_blue"] = StaticText("")
		self["key_menu"] = StaticText(_("MENU"))
		self["lab1"] = StaticText(_("norhap"))
		self["lab2"] = StaticText(_("Report problems to:"))
		self["lab3"] = StaticText(_("telegram @norhap"))
		self["lab4"] = StaticText(_("Sources are available at:"))
		self["lab5"] = StaticText(_("https://github.com/norhap"))
		self.BackupRunning = False
		self.BackupDirectory = " "
		if SystemInfo["canMultiBoot"]:
			self.mtdboot = SystemInfo["HasRootSubdir"]
		self.imagelist = {}
		self.getImageList = None
		self.onChangedEntry = []
		self.emlist = []
		self["list"] = MenuList(self.emlist)
		self.populate_List()
		self.activityTimer = eTimer()
		self.activityTimer.timeout.get().append(self.backupRunning)
		self.activityTimer.startLongTimer(10)
		self.Console = Console()

		global BackupTime
		BackupTime = 0
		if BackupTime > 0:
			t = localtime(BackupTime)
			backuptext = _("Next backup: ") + strftime(_("%a %e %b  %-H:%M"), t)
		else:
			backuptext = _("Next backup: ")
		if config.imagemanager.schedule.value:
			self["backupstatus"].setText(str(backuptext))
		if self.selectionChanged not in self["list"].onSelectionChanged:
			self["list"].onSelectionChanged.append(self.selectionChanged)

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
		try:
			size = statvfs(config.imagemanager.backuplocation.value)
			free = (size.f_bfree * size.f_frsize) // (1024 * 1024) // 1000
			if free > 0:
				self.BackupRunning = False
				for job in Components.Task.job_manager.getPendingJobs():
					if job.name.startswith(_("Image Manager")):
						self.BackupRunning = True
				if self.BackupRunning:
					self["key_green"].setText(_("View progress"))
				if config.imagemanager.backuplocation.value != "/" and not self.BackupRunning:
					self["key_green"].setText(_("New backupimage"))
				self.activityTimer.startLongTimer(1)
				self.refreshList()
		except OSError as err:
			print("%s" % err)

	def refreshUp(self):
		self["list"].instance.moveSelection(self["list"].instance.moveUp)

	def refreshDown(self):
		self["list"].instance.moveSelection(self["list"].instance.moveDown)

	def refreshList(self):
		if self.BackupDirectory == " ":
			return
		if config.imagemanager.backuplocation.value != "/":
			images = listdir(self.BackupDirectory)
			del self.emlist[:]
			mtimes = []
			for file in [x for x in images if path.splitext(x)[1] == ".zip" and MODEL in x]:
				mtimes.append((file, stat(self.BackupDirectory + file).st_mtime))  # (filname, mtime)
			for file in [x[0] for x in sorted(mtimes, key=lambda x: x[1], reverse=True)]:  # sort by mtime
				self.emlist.append(file)
			if len(self.emlist):
				self["list"].setList(self.emlist)
				self["list"].show()
				self["key_red"].setText(_("Delete"))
				self["key_blue"].setText(_("Flash"))
				self["key_yellow"].setText(_("Downloads"))
			else:
				self["key_red"].setText("")
				self["key_blue"].setText("")
				if config.imagemanager.backuplocation.value != "/":
					size = statvfs(config.imagemanager.backuplocation.value)
					free = (size.f_bfree * size.f_frsize) // (1024 * 1024) // 1000
					self["key_yellow"].setText(_("Downloads")) if free > 0 else self["key_yellow"].setText("")

	def getJobName(self, job):
		return "%s: %s (%d%%)" % (job.getStatustext(), job.name, int(100 * job.progress / float(job.end)))

	def showJobView(self, job):
		Components.Task.job_manager.in_background = False
		self.session.openWithCallback(self.JobViewCB, JobView, job, cancelable=False, backgroundable=False, afterEventChangeable=False)

	def JobViewCB(self, in_background):
		Components.Task.job_manager.in_background = in_background

	def populate_List(self):
		hotplugInfoDevice = self["lab6"].setText(_("Your mount has changed, restart enigma2 to updated.") if harddiskmanager.HDDList() else _("No device available."))
		if not mountpointchoices:
			self["myactions"] = ActionMap(["OkCancelActions", "MenuActions"], {
				"cancel": self.close,
				"menu": self.createSetup
			}, -1)
			self["list"].hide()
			self["key_red"].setText("")
			self["key_green"].setText("")
			self["key_yellow"].setText("")
			self["key_blue"].setText("")
			return hotplugInfoDevice
		else:
			try:
				size = statvfs(config.imagemanager.backuplocation.value)
				free = (size.f_bfree * size.f_frsize) // (1024 * 1024) // 1000
				if free == 0 and not mountpointchoices:
					self["myactions"] = ActionMap(["OkCancelActions", "MenuActions"], {
						"cancel": self.close,
						"menu": self.createSetup
					}, -1)
					self["lab6"].setText(_("No device available."))
				if config.imagemanager.backuplocation.value != "/" and not path.exists(config.imagemanager.backuplocation.value + '/imagebackups'):
					mkdir(config.imagemanager.backuplocation.value + '/imagebackups', 0o755)
				self["myactions"] = ActionMap(["ColorActions", "OkCancelActions", "DirectionActions", "MenuActions", "HelpActions"], {
					"cancel": self.close,
					"red": self.keyDelete,
					"green": self.greenPressed,
					"yellow": self.doDownload,
					"menu": self.createSetup,
					"ok": self.keyRestore,
					"blue": self.keyRestore,
					"up": self.refreshUp,
					"down": self.refreshDown,
					"displayHelp": self.doDownload
				}, -1)
				if "/media/net" not in config.imagemanager.backuplocation.value and "/media/autofs" not in config.imagemanager.backuplocation.value and free > 0:
					self["lab6"].setText(_("Storage Device:\n\n") + _("Mount: ") + " " + config.imagemanager.backuplocation.value + " " + _("Free space:") + " " + str(free) + _(" GB"))
				elif free > 0:
					self["lab6"].setText(_("Network server:\n\n") + _("Mount: ") + " " + config.imagemanager.backuplocation.value + " " + _("Free space:") + " " + str(free) + _(" GB"))
				else:
					self["lab6"].setText(_("Your mount has changed, restart enigma2 to updated."))
				self.BackupDirectory = config.imagemanager.backuplocation.value + "/imagebackups/" if not config.imagemanager.backuplocation.value.endswith("/") else config.imagemanager.backuplocation.value + "imagebackups/"
				if path.exists(self.BackupDirectory + config.imagemanager.folderprefix.value + "-" + imagetype + "-swapfile_backup"):
					system("swapoff " + self.BackupDirectory + config.imagemanager.folderprefix.value + "-" + imagetype + "-swapfile_backup")
					remove(self.BackupDirectory + config.imagemanager.folderprefix.value + "-" + imagetype + "-swapfile_backup")
				if self.BackupDirectory and free > 0:
					self["list"].show()
					self["key_red"].setText(_("Delete"))
					self["key_yellow"].setText(_("Downloads"))
					self["key_blue"].setText(_("Flash"))
				if self.BackupDirectory and not self.BackupRunning and free > 0:
					self["key_green"].setText(_("New backupimage"))
			except:
				self["key_green"].setText("")  # device lost, then actions cancel screen or actions menu is possible
				self["myactions"] = ActionMap(["OkCancelActions", "MenuActions"], {
					"cancel": self.close,
					"menu": self.createSetup
				}, -1)
				hotplugInfoDevice
				self["key_green"].setText("")
		self.refreshList()

	def createSetup(self):
		self.session.openWithCallback(self.setupDone, ImageManagerSetup)

	def doDownload(self):
		try:
			if config.imagemanager.backuplocation.value != "/":
				choices = [("Open Vision", config.imagemanager.imagefeed_OV), ("OpenATV", config.imagemanager.imagefeed_ATV), ("OpenPLi", config.imagemanager.imagefeed_PLi), ("OpenViX", config.imagemanager.imagefeed_ViX), ("OpenBh", config.imagemanager.imagefeed_OBH)]
				message = _("From which image library do you want to download?")
				self.session.openWithCallback(self.doDownloadCallback, MessageBox, message, list=sorted(sorted(choices, key=lambda choice: choice[0]), key=lambda choice: choice[0] == imagedistro, reverse=True), default=0, simple=True)
		except OSError as err:
			print("%s" % err)

	def doDownloadCallback(self, retval):  # retval will be the config element (or False, in the case of aborting the MessageBox).
		if retval:
			self.session.openWithCallback(self.refreshList, ImageManagerDownload, self.BackupDirectory, retval)

	def setupDone(self, retval=None):
		self.populate_List()
		self.doneConfiguring()

	def doneConfiguring(self):
		now = int(time())
		if config.imagemanager.schedule.value:
			if autoImageManagerTimer is not None:
				print("[ImageManager] Backup Schedule Enabled at", strftime("%c", localtime(now)))
				autoImageManagerTimer.backupupdate()
		else:
			if autoImageManagerTimer is not None:
				global BackupTime
				BackupTime = 0
				print("[ImageManager] Backup Schedule Disabled at", strftime("%c", localtime(now)))
				autoImageManagerTimer.backupstop()
		if BackupTime > 0:
			t = localtime(BackupTime)
			backuptext = _("Next backup: ") + strftime(_("%a %e %b  %-H:%M"), t)
		else:
			backuptext = _("Next backup: ")
		if config.imagemanager.schedule.value:
			self["backupstatus"].setText(str(backuptext))

	def keyDelete(self):
		try:
			if config.imagemanager.backuplocation.value != "/":
				self.sel = self["list"].getCurrent()
				if self.sel:
					message = _("Are you sure you want to delete this backup:\n ") + self.sel
					confirm_delete = self.session.openWithCallback(self.backupToDelete, MessageBox, message, MessageBox.TYPE_YESNO, default=False)
					confirm_delete.setTitle(_("Remove confirmation"))
		except OSError as err:
			print("%s" % err)

	def backupToDelete(self, answer):
		self.sel = self["list"].getCurrent()
		backupname = self.BackupDirectory + self.sel
		folderprefix = config.imagemanager.folderprefix.value + "-" + imagetype
		cmd = "rm -rf %s" % backupname
		if answer:
			if self.sel.startswith(folderprefix) and not self.BackupRunning or self.sel.endswith(".zip"):
				Console().ePopen(cmd)
			self.refreshList()

	def greenPressed(self):
		try:
			if config.imagemanager.backuplocation.value != "/":
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
		except OSError as err:
			print("%s" % err)

	def keyBackup(self):
		message = _("Do you want to create a full image backup?\nThis task can take about to complete.")
		ybox = self.session.openWithCallback(self.doBackup, MessageBox, message, MessageBox.TYPE_YESNO)
		ybox.setTitle(_("Backup confirmation"))

	def doBackup(self, answer):
		if answer is True:
			self.ImageBackup = ImageBackup(self.session)
			Components.Task.job_manager.AddJob(self.ImageBackup.createBackupJob())
			self.BackupRunning = True
			self["key_green"].setText(_("View progress"))
			for job in Components.Task.job_manager.getPendingJobs():
				if job.name.startswith(_("Image Manager")):
					break
			self.showJobView(job)

	def doSettingsBackup(self):
		from Plugins.SystemPlugins.Vision.BackupManager import BackupFiles
		self.BackupFiles = BackupFiles(self.session, False, True)
		Components.Task.job_manager.AddJob(self.BackupFiles.createBackupJob())
		Components.Task.job_manager.in_background = False
		for job in Components.Task.job_manager.getPendingJobs():
			if job.name.startswith(_("Backup manager")):
				break
		self.session.openWithCallback(self.keyRestore3, JobView, job, cancelable=False, backgroundable=False, afterEventChangeable=False)

	def keyRestore(self):
		self.sel = self["list"].getCurrent()  # (name, link)
		if not self.sel:
			return
		print("[ImageManager][keyRestore] self.sel getCurrentImage", self.sel, "   ", getCurrentImage())
		if getCurrentImage() == 0 and self.isVuKexecCompatibleImage(self.sel):  # only if Vu multiboot has been enabled and the image is compatible
			message = (_("Do you want to flash Recovery image?\nThis will change all eMMC slots.") if "VuSlot0" in self.sel else _("This selection will flash the Recovery image.\nWe advise flashing new image to a MultiBoot slot and restoring (default) settings backup.\nSelect \"NO\" to flash a MultiBoot slot."))
			ybox = self.session.openWithCallback(self.keyRestorez0, MessageBox, message, default=False)
			ybox.setTitle(_("Restore confirmation"))
		else:
			self.keyRestore1()

	def keyRestorez0(self, retval):
		print("[ImageManager][keyRestorez0] retval", retval)
		if retval:
			message = (_("Do you want to backup eMMC slots?\nThis will add from 1 -> 5 minutes per eMMC slot."))
			ybox = self.session.openWithCallback(self.keyRestorez1, MessageBox, message, default=False)
			ybox.setTitle(_("Confirmation copy eMMC slots"))
		else:
			self.keyRestore1()

	def keyRestorez1(self, retval):
		if retval:
			self.VuKexecCopyimage()
		else:
			self.multibootslot = 0												# set slot0 to be flashed
			self.Console.ePopen("umount /proc/cmdline", self.keyRestore3)		# tell ofgwrite not Vu Multiboot

	def keyRestore1(self):
		self.HasSDmmc = False
		self.multibootslot = 1
		self.MTDKERNEL = getMachineMtdKernel()
		self.MTDROOTFS = getMachineMtdRoot()
		if MODEL == "et8500" and path.exists("/proc/mtd"):
			self.dualboot = self.dualBoot()
		recordings = self.session.nav.getRecordings()
		if not recordings:
			next_rec_time = self.session.nav.RecordTimer.getNextRecordingTime()
		if recordings or (next_rec_time > 0 and (next_rec_time - time()) < 360):
			message = _("Recording(s) are in progress or coming up in few seconds!\nDo you still want to flash image\n%s?") % self.sel
		else:
			message = _("Do you want to flash image?\n%s") % self.sel
		if SystemInfo["canMultiBoot"] is False:
			if config.imagemanager.autosettingsbackup.value:
				self.doSettingsBackup()
			else:
				self.keyRestore3()
		if SystemInfo["HiSilicon"]:
			if pathExists("/dev/sda4"):
				self.HasSDmmc = True
		imagedict = getImagelist()
		choices = []
		currentimageslot = getCurrentImage()
		for x in imagedict.keys():
			choices.append(((_("slot%s - %s (current image)") if x == currentimageslot else _("slot%s - %s")) % (x, imagedict[x]["imagename"]), (x)))
		self.session.openWithCallback(self.keyRestore2, MessageBox, message, list=choices, default=False, simple=True)

	def keyResstore0(self, answer):
		if answer:
			if SystemInfo["canMultiBoot"] is False:
				if config.imagemanager.autosettingsbackup.value:
					self.doSettingsBackup()
				else:
					self.keyRestore3()
			if SystemInfo["HiSilicon"]:
				if pathExists("/dev/sda4"):
					self.HasSDmmc = True
			imagedict = getImagelist()
			choices = []
			currentimageslot = getCurrentImage()
			for x in imagedict.keys():
				choices.append(((_("slot%s  %s current image") if x == currentimageslot else _("slot%s  %s")) % (x, imagedict[x]["imagename"]), (x)))
			self.session.openWithCallback(self.keyRestore2, MessageBox, self.message, list=choices, default=currentimageslot, simple=True)

	def keyRestore2(self, retval):
		if retval:
			if SystemInfo["canMultiBoot"]:
				self.multibootslot = retval
				print("ImageManager", retval)
				self.MTDKERNEL = SystemInfo["canMultiBoot"][self.multibootslot]["kernel"].split("/")[2]
				if SystemInfo["HasMultibootMTD"]:
					self.MTDROOTFS = SystemInfo["canMultiBoot"][self.multibootslot]["device"]
				else:
					self.MTDROOTFS = SystemInfo["canMultiBoot"][self.multibootslot]["device"].split("/")[2]
			if SystemInfo["HiSilicon"] and getCurrentImage() >= 4 and self.multibootslot < 4:
				self.session.open(MessageBox, _("ImageManager - %s - cannot flash eMMC slot from sd card slot.") % MODEL, MessageBox.TYPE_INFO, timeout=10)
				return
			if self.sel:
				if config.imagemanager.autosettingsbackup.value:
					self.doSettingsBackup()
				else:
					self.keyRestore3()
			else:
				self.session.open(MessageBox, _("There is no image to flash."), MessageBox.TYPE_INFO, timeout=10)

	def keyRestore3(self, *args, **kwargs):
		self.restore_infobox = self.session.open(MessageBox, _("Please wait while the flash prepares."), MessageBox.TYPE_INFO, timeout=240, enable_input=False)
		if "/media/autofs" in config.imagemanager.backuplocation.value or "/media/net" in config.imagemanager.backuplocation.value:
			self.TEMPDESTROOT = tempfile.mkdtemp(prefix="imageRestore")
		else:
			self.TEMPDESTROOT = self.BackupDirectory + "imagerestore"
		if self.sel.endswith(".zip"):
			if config.imagemanager.backuplocation.value != "/" and not path.exists(self.TEMPDESTROOT):
				mkdir(self.TEMPDESTROOT, 0o755)
			self.Console.ePopen("unzip -o %s%s -d %s" % (self.BackupDirectory, self.sel, self.TEMPDESTROOT), self.keyRestore4)
		else:
			self.TEMPDESTROOT = self.BackupDirectory + self.sel
			self.keyRestore4(0, 0)

	def keyRestore4(self, result, retval, extra_args=None):
		if retval == 0:
			self.session.openWithCallback(self.restore_infobox.close, MessageBox, _("Flash image unzip successful."), MessageBox.TYPE_INFO, timeout=4)
			if MODEL == "et8500" and self.dualboot:
				message = _("ET8500 Multiboot: Yes to restore OS1 No to restore OS2:\n ") + self.sel
				ybox = self.session.openWithCallback(self.keyRestore5_ET8500, MessageBox, message)
				ybox.setTitle(_("ET8500 Image Restore"))
			else:
				MAINDEST = "%s/%s" % (self.TEMPDESTROOT, imagedir)
				if pathExists("%s/SDAbackup" % MAINDEST) and self.multibootslot != 1:
					self.session.open(MessageBox, _("Multiboot only able to restore this backup to MMC slot1"), MessageBox.TYPE_INFO, timeout=20)
					print("[ImageManager] SF8008 MMC restore to SDcard failed:\n", end=' ')
					self.close()
				else:
					self.keyRestore6(0)
		else:
			self.session.openWithCallback(self.restore_infobox.close, MessageBox, _("Bad image file unzip Error:\n%s") % result, MessageBox.TYPE_ERROR, timeout=20)
			print("[ImageManager] unzip failed:\n", result)
			self.close()

	def keyRestore5_ET8500(self, answer):
		if answer:
			self.keyRestore6(0)
		else:
			self.keyRestore6(1)

	def keyRestore6(self, ret):
		MAINDEST = "%s/%s" % (self.TEMPDESTROOT, imagedir)
		if ret == 0:
			CMD = "/usr/bin/ofgwrite -r -k '%s'" % MAINDEST
			# normal non multiboot receiver
			if SystemInfo["canMultiBoot"]:
				if self.multibootslot == 0 and SystemInfo["hasKexec"]:  # reset Vu Multiboot slot0
					kz0 = getMachineMtdKernel()
					rz0 = getMachineMtdRoot()
					CMD = "/usr/bin/ofgwrite -kkz0 -rrz0 '%s'" % MAINDEST  # slot0 treat as kernel/root only multiboot receiver
				elif SystemInfo["HiSilicon"] and SystemInfo["canMultiBoot"][self.multibootslot]["rootsubdir"] is None:  # sf8008 type receiver using SD card in multiboot
					CMD = "/usr/bin/ofgwrite -r%s -k%s -m0 '%s'" % (self.MTDROOTFS, self.MTDKERNEL, MAINDEST)
					print("[ImageManager] running commnd:%s slot = %s" % (CMD, self.multibootslot))
					if fileExists("/boot/STARTUP") and fileExists("/boot/STARTUP_6"):
						copyfile("/boot/STARTUP_%s" % self.multibootslot, "/boot/STARTUP")
				elif SystemInfo["hasKexec"]:
					if SystemInfo["HasKexecUSB"] and "mmcblk" not in self.MTDROOTFS:
						CMD = "/usr/bin/ofgwrite -r%s -kzImage -s'%s/linuxrootfs' -m%s '%s'" % (self.MTDROOTFS, MODEL[2:], self.multibootslot, MAINDEST)
					else:
						CMD = "/usr/bin/ofgwrite -r%s -kzImage -m%s '%s'" % (self.MTDROOTFS, self.multibootslot, MAINDEST)
					print("[ImageManager] running commnd:%s slot = %s" % (CMD, self.multibootslot))
				else:
					CMD = "/usr/bin/ofgwrite -r -k -m%s '%s'" % (self.multibootslot, MAINDEST)  # Normal multiboot
			elif SystemInfo["HasH9SD"]:
				if fileHas("/proc/cmdline", "root=/dev/mmcblk0p1") is True and fileExists("%s/rootfs.tar.bz2" % MAINDEST):  # h9 using SD card
					CMD = "/usr/bin/ofgwrite -rmmcblk0p1 '%s'" % MAINDEST
				elif fileExists("%s/rootfs.ubi" % MAINDEST) and fileExists("%s/rootfs.tar.bz2" % MAINDEST):  # h9 no SD card - build has both roots causes ofgwrite issue
					rename("%s/rootfs.tar.bz2" % MAINDEST, "%s/xx.txt" % MAINDEST)
		else:
			CMD = "/usr/bin/ofgwrite -rmtd4 -kmtd3  %s/" % MAINDEST  # Xtrend ET8500 with OS2 multiboot
		print("[ImageManager] running commnd:", CMD)
		self.Console.ePopen(CMD, self.ofgwriteResult)
		fbClass.getInstance().lock()

	def ofgwriteResult(self, result, retval, extra_args=None):
		from Screens.FlashImage import MultibootSelection
		fbClass.getInstance().unlock()
		print("[ImageManager] ofgwrite retval:", retval)
		if retval == 0:
			if SystemInfo["HiSilicon"] and SystemInfo["HasRootSubdir"] is False and self.HasSDmmc is False:  # sf8008 receiver 1 eMMC parition, No SD card
				self.session.open(TryQuitMainloop, 2)
			if SystemInfo["canMultiBoot"]:
				print("[ImageManager] slot %s result %s\n" % (self.multibootslot, str(result)))
				tmp_dir = tempfile.mkdtemp(prefix="ImageManagerFlash")
				Console().ePopen("mount %s %s" % (self.mtdboot, tmp_dir))
				if pathExists(path.join(tmp_dir, "STARTUP")):
					copyfile(path.join(tmp_dir, SystemInfo["canMultiBoot"][self.multibootslot]["startupfile"].replace("boxmode=12'", "boxmode=1'")), path.join(tmp_dir, "STARTUP"))
				else:
					if path.exists(config.imagemanager.backuplocation.value + "/imagebackups/imagerestore"):
						try:
							rmtree(config.imagemanager.backuplocation.value + "/imagebackups/imagerestore")
						except Exception:
							pass
				Console().ePopen('umount %s' % tmp_dir)
				if not path.ismount(tmp_dir):
					rmdir(tmp_dir)
				self.session.openWithCallback(self.close, MultibootSelection)
			else:
				self.session.open(TryQuitMainloop, 2)
		else:
			self.session.openWithCallback(self.restore_infobox.close, MessageBox, _("ofgwrite error (also sent to any debug log):\n%s") % result, MessageBox.TYPE_INFO, timeout=20)
			print("[ImageManager] ofgwrite result failed:\n", result)

	def dualBoot(self):
		rootfs2 = False
		kernel2 = False
		with open("/proc/mtd")as f:
			L = f.readlines()
			for x in L:
				if "rootfs2" in x:
					rootfs2 = True
				if "kernel2" in x:
					kernel2 = True
			if rootfs2 and kernel2:
				return True
			else:
				return False

	def isVuKexecCompatibleImage(self, name):
		retval = False
		if "VuSlot0" in name:
			retval = True
		else:
			name_split = name.split("-")
			if len(name_split) > 1 and name_split[0] in ("openbh", "openvix", "openvision") and name[-8:] == "_usb.zip":  # "_usb.zip" only in build server images
				parts = name_split[1].split(".")
				if len(parts) > 1 and parts[0].isnumeric() and parts[1].isnumeric():
					version = float(parts[0] + "." + parts[1])
					if name_split[0] == "openbh" and version > 5.1:
						retval = True
					if name_split[0] == "openvix" and (version > 6.3 or version == 6.3 and len(parts) > 2 and parts[2].isnumeric() and int(parts[2]) > 2):  # greater than 6.2.002
						retval = True
					if name_split[0] == "openvision":
						retval = True
		return retval

	def VuKexecCopyimage(self):
		installedHDD = False
		with open("/proc/mounts", "r") as fd:
			lines = fd.readlines()
		result = [line.strip().split(" ") for line in lines]
		print("[ImageManager][VuKexecCopyimage] result", result)
		for item in result:
			if '/media/hdd' in item[1] and "/dev/sd" in item[0]:
				installedHDD = True
				break
		if installedHDD and pathExists("/media/hdd"):
			if not pathExists("/media/hdd/%s" % MODEL):
				mkdir("/media/hdd/%s" % MODEL)
			for usbslot in range(1, 4):
				if pathExists("/linuxrootfs%s" % usbslot):
					if pathExists("/media/hdd/%s/linuxrootfs%s/" % (MODEL, usbslot)):
						rmtree("/media/hdd/%s/linuxrootfs%s" % (MODEL, usbslot), ignore_errors=True)
					Console().ePopen("cp -R /linuxrootfs%s . /media/hdd/%s/" % (usbslot, MODEL))
		if not installedHDD:
			self.session.open(MessageBox, _("ImageManager - no HDD unable to backup Vu+ Multiboot eMMC slots"), MessageBox.TYPE_INFO, timeout=5)
		self.multibootslot = 0												# set slot0 to be flashed
		self.Console.ePopen("umount /proc/cmdline", self.keyRestore3)		# tell ofgwrite not Vu Multiboot


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
			print("[ImageManager] Backup Schedule Enabled at ", strftime("%c", localtime(now)))
			if now > 1262304000:
				self.backupupdate()
			else:
				print("[ImageManager] Backup Time not yet set.")
				BackupTime = 0
				self.backupactivityTimer.start(36000)
		else:
			BackupTime = 0
			print("[ImageManager] Backup Schedule Disabled at", strftime("(now=%c)", localtime(now)))
			self.backupactivityTimer.stop()

	def backupupdatedelay(self):
		self.backupactivityTimer.stop()
		self.backupupdate()

	def getBackupTime(self):
		backupclock = config.imagemanager.scheduletime.value
		#
		# Work out the time of the *NEXT* backup - which is the configured clock
		# time on the nth relevant day after the last recorded backup day.
		# The last backup time will have been set as 12:00 on the day it
		# happened. All we use is the actual day from that value.
		#
		lastbkup_t = int(config.imagemanager.lastbackup.value)
		if config.imagemanager.repeattype.value == "daily":
			nextbkup_t = lastbkup_t + 24 * 3600
		elif config.imagemanager.repeattype.value == "weekly":
			nextbkup_t = lastbkup_t + 7 * 24 * 3600
		elif config.imagemanager.repeattype.value == "monthly":
			nextbkup_t = lastbkup_t + 30 * 24 * 3600
		nextbkup = localtime(nextbkup_t)
		return int(mktime((nextbkup.tm_year, nextbkup.tm_mon, nextbkup.tm_mday, backupclock[0], backupclock[1], 0, nextbkup.tm_wday, nextbkup.tm_yday, nextbkup.tm_isdst)))

	def backupupdate(self, atLeast=0):
		self.backuptimer.stop()
		global BackupTime
		BackupTime = self.getBackupTime()
		now = int(time())
		if BackupTime > 0:
			if BackupTime < now + atLeast:
				self.backuptimer.startLongTimer(60)  # Backup missed - run it 60s from now
				print("[ImageManager] Backup Time overdue - running in 60s")
			else:
				delay = BackupTime - now  # Backup in future - set the timer...
				self.backuptimer.startLongTimer(delay)
		else:
			BackupTime = -1
		print("[ImageManager] Backup Time set to", strftime("%c", localtime(BackupTime)), strftime("(now=%c)", localtime(now)))
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
			print("[ImageManager] Backup onTimer occured at", strftime("%c", localtime(now)))
			from Screens.Standby import inStandby

			if not inStandby and config.imagemanager.query.value:
				message = _("Your receiver is about to create a full image backup, this can take about 6 minutes to complete.\nDo you want to allow this?")
				ybox = self.session.openWithCallback(self.doBackup, MessageBox, message, MessageBox.TYPE_YESNO, timeout=30)
				ybox.setTitle("Scheduled backup.")
			else:
				print("[ImageManager] in Standby or no querying, so just running backup", strftime("%c", localtime(now)))
				self.doBackup(True)
		else:
			print("[ImageManager] We are not close enough", strftime("%c", localtime(now)))
			self.backupupdate(60)

	def doBackup(self, answer):
		now = int(time())
		if answer is False:
			if config.imagemanager.backupretrycount.value < 2:
				print("[ImageManager] Number of retries", config.imagemanager.backupretrycount.value)
				print("[ImageManager] Backup delayed.")
				repeat = config.imagemanager.backupretrycount.value
				repeat += 1
				config.imagemanager.backupretrycount.setValue(repeat)
				BackupTime = now + (int(config.imagemanager.backupretry.value) * 60)
				print("[ImageManager] Backup Time now set to", strftime("%c", localtime(BackupTime)), strftime("(now=%c)", localtime(now)))
				self.backuptimer.startLongTimer(int(config.imagemanager.backupretry.value) * 60)
			else:
				atLeast = 60
				print("[ImageManager] Enough Retries, delaying till next schedule.", strftime("%c", localtime(now)))
				self.session.open(MessageBox, _("Enough retries, delaying till next schedule."), MessageBox.TYPE_INFO, timeout=10)
				config.imagemanager.backupretrycount.setValue(0)
				self.backupupdate(atLeast)
		else:
			print("[ImageManager] Running Backup", strftime("%c", localtime(now)))
			self.ImageBackup = ImageBackup(self.session)
			Components.Task.job_manager.AddJob(self.ImageBackup.createBackupJob())
			#      Note that fact that the job has been *scheduled*.
			#      We do *not* just note successful completion, as that would
			#      result in a loop on issues such as disk-full.
			#      Also all that we actually want to know is the day, not the time, so
			#      we actually remember midday, which avoids problems around DLST changes
			#      for backups scheduled within an hour of midnight.
			#
			sched = localtime(time())
			sched_t = int(mktime((sched.tm_year, sched.tm_mon, sched.tm_mday, 12, 0, 0, sched.tm_wday, sched.tm_yday, sched.tm_isdst)))
			config.imagemanager.lastbackup.value = sched_t
			config.imagemanager.lastbackup.save()
		# self.close()


class ImageBackup(Screen):
	skin = """
	<screen name="VISIONImageManager" position="center,center" size="560,400">
		<ePixmap pixmap="buttons/red.png" position="0,0" size="140,40" alphaTest="blend"/>
		<ePixmap pixmap="buttons/green.png" position="140,0" size="140,40" alphaTest="blend"/>
		<ePixmap pixmap="buttons/yellow.png" position="280,0" size="140,40" alphaTest="blend"/>
		<ePixmap pixmap="buttons/blue.png" position="420,0" size="140,40" alphaTest="blend"/>
		<widget name="key_red" position="0,0" zPosition="1" size="140,40" font="Regular;20" horizontalAlignment="center" verticalAlignment="center" backgroundColor="#9f1313" transparent="1"/>
		<widget name="key_green" position="140,0" zPosition="1" size="140,40" font="Regular;20" horizontalAlignment="center" verticalAlignment="center" backgroundColor="#1f771f" transparent="1"/>
		<widget name="key_yellow" position="280,0" zPosition="1" size="140,40" font="Regular;20" horizontalAlignment="center" verticalAlignment="center" backgroundColor="#a08500" transparent="1"/>
		<widget name="key_blue" position="420,0" zPosition="1" size="140,40" font="Regular;20" horizontalAlignment="center" verticalAlignment="center" backgroundColor="#18188b" transparent="1"/>
		<widget name="lab6" position="0,50" size="560,50" font="Regular; 18" zPosition="2" transparent="0" horizontalAlignment="center"/>
		<widget name="list" position="10,105" size="540,260" scrollbarMode="showOnDemand"/>
		<applet type="onLayoutFinish">
			self["list"].instance.setItemHeight(25)
		</applet>
	</screen>"""

	def __init__(self, session, updatebackup=False):
		Screen.__init__(self, session)
		self.Console = Console()
		self.errorCallback = None
		self.BackupDevice = config.imagemanager.backuplocation.value
		print("[ImageManager] Device: " + self.BackupDevice)
		self.BackupDirectory = config.imagemanager.backuplocation.value + "/imagebackups/" if not config.imagemanager.backuplocation.value.endswith("/") else config.imagemanager.backuplocation.value + "imagebackups/"
		print("[ImageManager] Directory: " + self.BackupDirectory)
		self.BackupDate = strftime("%Y%m%d_%H%M%S", localtime())
		self.TMPDIR = self.BackupDirectory + config.imagemanager.folderprefix.value + "-" + imagetype + "-temp"
		self.TMPMOUNTDIR = self.BackupDirectory + config.imagemanager.folderprefix.value + "-" + imagetype + "-mount"
		backupType = "-"
		if updatebackup:
			backupType = "-SoftwareUpdate-"
		imageSubBuild = ""
		if imagetype != "develop":
			imageSubBuild = ".%s" % getImageDevBuild()
		self.MAINDESTROOT = self.BackupDirectory + config.imagemanager.folderprefix.value + "-" + imagetype + "-" + backupimage + "-" + MODEL + "-" + self.BackupDate
		self.KERNELFILE = kernelfile
		self.ROOTFSFILE = getMachineRootFile()
		self.MAINDEST = self.MAINDESTROOT + "/" + imagedir + "/"
		self.MAINDEST2 = self.MAINDESTROOT + "/"
		self.MODEL = MODEL
		self.MCBUILD = getMachineBuild()
		self.IMAGEDISTRO = imagedistro
		self.DISTROVERSION = imageversion
		self.DISTROBUILD = backupimage
		self.KERNELBIN = kernelfile
		self.UBINIZE_ARGS = getMachineUBINIZE()
		self.MKUBIFS_ARGS = getMachineMKUBIFS()
		self.ROOTFSTYPE = imagefs.strip()
		self.ROOTFSSUBDIR = "none"
		self.VuSlot0 = ""
		self.EMMCIMG = "none"
		self.MTDBOOT = "none"
		if SystemInfo["canBackupEMC"]:
			(self.EMMCIMG, self.MTDBOOT) = SystemInfo["canBackupEMC"]
		print("[ImageManager] canBackupEMC:", SystemInfo["canBackupEMC"])
		self.KERN = "mmc"
		self.rootdir = 0
		if SystemInfo["canMultiBoot"]:
			slot = getCurrentImage()
			if SystemInfo["hasKexec"]:
				self.MTDKERNEL = getMachineMtdKernel() if slot == 0 else SystemInfo["canMultiBoot"][slot]["kernel"]
				self.MTDROOTFS = getMachineMtdRoot() if slot == 0 else SystemInfo["canMultiBoot"][slot]["device"].split("/")[2]
				self.VuSlot0 = "-VuSlot0" if slot == 0 else ""
			else:
				self.MTDKERNEL = SystemInfo["canMultiBoot"][slot]["kernel"].split("/")[2]
			if SystemInfo["HasMultibootMTD"]:
				self.MTDROOTFS = SystemInfo["canMultiBoot"][slot]["device"]  # sfx60xx ubi0:ubifs not mtd=
			elif not SystemInfo["hasKexec"]:
				self.MTDROOTFS = SystemInfo["canMultiBoot"][slot]["device"].split("/")[2]
			if SystemInfo["HasRootSubdir"] and slot != 0:
				self.ROOTFSSUBDIR = SystemInfo["canMultiBoot"][slot]["rootsubdir"]
		else:
			self.MTDKERNEL = getMachineMtdKernel()
			self.MTDROOTFS = getMachineMtdRoot()
		if getMachineBuild() == "gb7252" or MODEL == "gbx34k":
			self.GB4Kbin = "boot.bin"
			self.GB4Krescue = "rescue.bin"
		if "sda" in self.MTDKERNEL:
			self.KERN = "sda"
		print("[ImageManager] hasKexec:", SystemInfo["hasKexec"])
		print("[ImageManager] Model:", self.MODEL)
		print("[ImageManager] Machine Build:", self.MCBUILD)
		print("[ImageManager] Kernel File:", self.KERNELFILE)
		print("[ImageManager] Root File:", self.ROOTFSFILE)
		print("[ImageManager] MTD Kernel:", self.MTDKERNEL)
		print("[ImageManager] MTD Root:", self.MTDROOTFS)
		print("[ImageManager] ROOTFSSUBDIR:", self.ROOTFSSUBDIR)
		print("[ImageManager] ROOTFSTYPE:", self.ROOTFSTYPE)
		print("[ImageManager] MAINDESTROOT:", self.MAINDESTROOT)
		print("[ImageManager] MAINDEST:", self.MAINDEST)
		print("[ImageManager] MAINDEST2:", self.MAINDEST2)
		print("[ImageManager] TMPDIR:", self.TMPDIR)
		print("[ImageManager] TMPMOUNTDIR:", self.TMPMOUNTDIR)
		print("[ImageManager] EMMCIMG:", self.EMMCIMG)
		print("[ImageManager] MTDBOOT:", self.MTDBOOT)
		self.swapdevice = ""
		self.RamChecked = False
		self.SwapCreated = False
		self.Stage1Completed = False
		self.Stage2Completed = False
		self.Stage3Completed = False
		self.Stage4Completed = False
		self.Stage5Completed = False
		self.Stage6Completed = False

	def createBackupJob(self):
		job = Components.Task.Job(_("Image Manager"))

		task = Components.Task.PythonTask(job, _("Setting up..."))
		task.work = self.JobStart
		task.weighting = 5

		task = Components.Task.ConditionTask(job, _("Checking free RAM.."), timeoutCount=10)
		task.check = lambda: self.RamChecked
		task.weighting = 5

		task = Components.Task.ConditionTask(job, _("Creating SWAP.."), timeoutCount=120)
		task.check = lambda: self.SwapCreated
		task.weighting = 5

		task = Components.Task.PythonTask(job, _("Backing up kernel..."))
		task.work = self.doBackup1
		task.weighting = 5

		task = Components.Task.ConditionTask(job, _("Backing up kernel..."), timeoutCount=900)
		task.check = lambda: self.Stage1Completed
		task.weighting = 35

		task = Components.Task.PythonTask(job, _("Backing up root file system..."))
		task.work = self.doBackup2
		task.weighting = 5

		task = Components.Task.ConditionTask(job, _("Backing up root file system..."), timeoutCount=2700)
		task.check = lambda: self.Stage2Completed
		task.weighting = 15

		task = Components.Task.PythonTask(job, _("Backing up eMMC partitions for USB flash ..."))
		task.work = self.doBackup3
		task.weighting = 5

		task = Components.Task.ConditionTask(job, _("Backing up eMMC partitions for USB flash..."), timeoutCount=2700)
		task.check = lambda: self.Stage3Completed
		task.weighting = 15

		task = Components.Task.PythonTask(job, _("Removing temp mounts..."))
		task.work = self.doBackup4
		task.weighting = 5

		task = Components.Task.ConditionTask(job, _("Removing temp mounts..."), timeoutCount=30)
		task.check = lambda: self.Stage4Completed
		task.weighting = 5

		task = Components.Task.PythonTask(job, _("Moving to backup Location..."))
		task.work = self.doBackup5
		task.weighting = 5

		task = Components.Task.ConditionTask(job, _("Moving to backup Location..."), timeoutCount=30)
		task.check = lambda: self.Stage5Completed
		task.weighting = 5

		task = Components.Task.PythonTask(job, _("Creating zip..."))
		task.work = self.doBackup6
		task.weighting = 5

		task = Components.Task.ConditionTask(job, _("Creating zip..."), timeoutCount=2700)
		task.check = lambda: self.Stage6Completed
		task.weighting = 5

		task = Components.Task.PythonTask(job, _("Backup complete."))
		task.work = self.BackupComplete
		task.weighting = 5

		return job

	def JobStart(self):
		try:
			if config.imagemanager.backuplocation.value != "/" and not path.exists(self.BackupDirectory):
				mkdir(self.BackupDirectory, 0o755)
			if path.exists(self.BackupDirectory + config.imagemanager.folderprefix.value + "-" + imagetype + "-swapfile_backup"):
				system("swapoff " + self.BackupDirectory + config.imagemanager.folderprefix.value + "-" + imagetype + "-swapfile_backup")
				remove(self.BackupDirectory + config.imagemanager.folderprefix.value + "-" + imagetype + "-swapfile_backup")
			s = statvfs(self.BackupDevice)
			free = (s.f_bsize * s.f_bavail) // (1024 * 1024)
			if int(free) < 200:
				AddPopupWithCallback(
					self.BackupComplete,
					_("The backup location does not have enough free space." + "\n" + self.BackupDevice + "only has " + str(free) + "MB free."),
					MessageBox.TYPE_INFO,
					10,
					"RamCheckFailedNotification"
				)
			else:
				self.MemCheck()
		except Exception as err:
			print("[ImageManager] JobStart Error: %s" % err)
			if self.errorCallback:
				self.errorCallback(err)

	def MemCheck(self):
		memfree = 0
		swapfree = 0
		with open("/proc/meminfo", "r") as f:
			for line in f.readlines():
				if line.find("MemFree") != -1:
					parts = line.strip().split()
					memfree = int(parts[1])
				elif line.find("SwapFree") != -1:
					parts = line.strip().split()
					swapfree = int(parts[1])
		TotalFree = memfree + swapfree
		print("[ImageManager] Stage1: Free Mem", TotalFree)
		if int(TotalFree) < 3000:
			supported_filesystems = frozenset(("ext4", "ext3", "ext2"))
			candidates = []
			mounts = getProcMounts()
			for partition in harddiskmanager.getMountedPartitions(False, mounts):
				if partition.filesystem(mounts) in supported_filesystems:
					candidates.append((partition.description, partition.mountpoint))
			for swapdevice in candidates:
				self.swapdevice = swapdevice[1]
			if self.swapdevice:
				print("[ImageManager] Stage1: Creating SWAP file.")
				self.RamChecked = True
				self.MemCheck2()
			else:
				print("[ImageManager] Sorry, not enough free RAM found, and no physical devices that supports SWAP attached")
				AddPopupWithCallback(
					self.BackupComplete,
					_("Sorry, not enough free RAM found, and no physical devices that supports SWAP attached. Can't create SWAP file on network or fat32 file-systems, unable to make backup."),
					MessageBox.TYPE_INFO,
					10,
					"RamCheckFailedNotification"
				)
		else:
			print("[ImageManager] Stage1: Found Enough RAM")
			self.RamChecked = True
			self.SwapCreated = True

	def MemCheck2(self):
		self.Console.ePopen("dd if=/dev/zero of=" + self.swapdevice + config.imagemanager.folderprefix.value + "-" + imagetype + "-swapfile_backup bs=1024 count=61440", self.MemCheck3)

	def MemCheck3(self, result, retval, extra_args=None):
		if retval == 0:
			self.Console.ePopen("mkswap " + self.swapdevice + config.imagemanager.folderprefix.value + "-" + imagetype + "-swapfile_backup", self.MemCheck4)

	def MemCheck4(self, result, retval, extra_args=None):
		if retval == 0:
			self.Console.ePopen("swapon " + self.swapdevice + config.imagemanager.folderprefix.value + "-" + imagetype + "-swapfile_backup", self.MemCheck5)

	def MemCheck5(self, result, retval, extra_args=None):
		self.SwapCreated = True

	def doBackup1(self):
		try:
			if config.imagemanager.backuplocation.value != "/":
				print("[ImageManager] Stage 1: Creating tmp folders.", self.BackupDirectory)
				print("[ImageManager] Stage 1: Creating backup folders.")
				mount = self.TMPMOUNTDIR + "/root/"
				for folder in ["linuxrootfs1", "proc"]:
					if path.exists(mount + folder):
						return self.session.open(TryQuitMainloop, 2)
				if path.exists(self.TMPDIR):
					rmtree(self.TMPDIR)
				mkdir(self.TMPDIR, 0o644)
				if path.exists(self.TMPMOUNTDIR):
					rmtree(self.TMPMOUNTDIR)
				makedirs(self.TMPMOUNTDIR, 0o644)
				makedirs(self.TMPMOUNTDIR + "/root", 0o644)
				makedirs(self.MAINDESTROOT, 0o644)
				self.commands = []
				makedirs(self.MAINDEST, 0o644)
			if SystemInfo["canMultiBoot"]:
				slot = getCurrentImage()
				print("[ImageManager] Stage 1: Making kernel image.")
			if "bin" or "uImage" in self.KERNELFILE:
				if BRAND == "Vu+":
					if SystemInfo["hasKexec"]:
						# boot = "boot" if slot > 0 and slot < 4 else "dev/%s/%s"  %(self.MTDROOTFS, self.ROOTFSSUBDIR)
						boot = "boot"
						self.command = "dd if=/%s/%s of=%s/vmlinux.bin" % (boot, SystemInfo["canMultiBoot"][slot]["kernel"].rsplit("/", 1)[1], self.TMPDIR) if slot != 0 else "dd if=/dev/%s of=%s/vmlinux.bin" % (self.MTDKERNEL, self.TMPDIR)
					else:
						self.command = "dd if=/dev/%s of=%s/vmlinux.bin" % (self.MTDKERNEL, self.TMPDIR)
				else:
					self.command = "dd if=/dev/%s of=%s/kernel.bin" % (self.MTDKERNEL, self.TMPDIR)
			else:
				self.command = "nanddump /dev/%s -f %s/vmlinux.gz" % (self.MTDKERNEL, self.TMPDIR)
			self.Console.ePopen(self.command, self.Stage1Complete)
		except OSError as err:
			print("[ImageManager] doBackup1 Error: %s" % err)
			if self.errorCallback:
				self.errorCallback(err)
			else:
				self.session.open(MessageBox, _('Device is not available.\nError: %s\n\nPress RED button in next screen \"Job cancel\"') % err, MessageBox.TYPE_ERROR, timeout=15)

	def Stage1Complete(self, result, retval, extra_args=None):
		if retval == 0:
			self.Stage1Completed = True
			print("[ImageManager] Stage1: Complete.")

	def doBackup2(self):
		print("[ImageManager] Stage2: Making root Image.")
		try:
			if "jffs2" in self.ROOTFSTYPE.split():
				print("[ImageManager] Stage2: JFFS2 Detected.")
				self.ROOTFSTYPE = "jffs2"
				if MODEL == "gb800solo":
					JFFS2OPTIONS = " --disable-compressor=lzo -e131072 -l -p125829120"
				else:
					JFFS2OPTIONS = " --disable-compressor=lzo --eraseblock=0x20000 -n -l"
				self.commands.append("mount --bind / %s/root" % self.TMPMOUNTDIR)
				self.commands.append("mkfs.jffs2 --root=%s/root --faketime --output=%s/rootfs.jffs2 %s" % (self.TMPMOUNTDIR, self.TMPDIR, JFFS2OPTIONS))
			elif "ubi" in self.ROOTFSTYPE.split():
				print("[ImageManager] Stage2: UBIFS Detected.")
				self.ROOTFSTYPE = "ubifs"
				with open("%s/ubinize.cfg" % self.TMPDIR, "w") as output:
					output.write("[ubifs]\n")
					output.write("mode=ubi\n")
					output.write("image=%s/root.ubi\n" % self.TMPDIR)
					output.write("vol_id=0\n")
					output.write("vol_type=dynamic\n")
					output.write("vol_name=rootfs\n")
					output.write("vol_flags=autoresize\n")

				self.commands.append("mount -o bind,ro / %s/root" % self.TMPMOUNTDIR)
				if MODEL in ("h9", "i55plus"):
					with open("/proc/cmdline", "r") as z:
						if SystemInfo["HasMMC"] and "root=/dev/mmcblk0p1" in z.read():
							self.ROOTFSTYPE = "tar.bz2"
							self.commands.append("/bin/tar -jcf %s/rootfs.tar.bz2 -C %s/root --exclude ./var/nmbd --exclude ./.resizerootfs --exclude ./.resize-rootfs --exclude ./.resize-linuxrootfs --exclude ./.resize-userdata --exclude ./var/lib/samba/private/msg.sock ." % (self.TMPDIR, self.TMPMOUNTDIR))
							self.commands.append("/usr/bin/bzip2 %s/rootfs.tar" % self.TMPDIR)
						else:
							self.commands.append("touch %s/root.ubi" % self.TMPDIR)
							self.commands.append("mkfs.ubifs -r %s/root -o %s/root.ubi %s" % (self.TMPMOUNTDIR, self.TMPDIR, self.MKUBIFS_ARGS))
							self.commands.append("ubinize -o %s/rootfs.ubifs %s %s/ubinize.cfg" % (self.TMPDIR, self.UBINIZE_ARGS, self.TMPDIR))
						self.commands.append("echo \" \"")
						self.commands.append('echo "' + _("Create:") + " fastboot dump" + '"')
						self.commands.append("dd if=/dev/mtd0 of=%s/fastboot.bin" % self.TMPDIR)
						self.commands.append("dd if=/dev/mtd0 of=%s/fastboot.bin" % self.MAINDEST2)
						self.commands.append('echo "' + _("Create:") + " bootargs dump" + '"')
						self.commands.append("dd if=/dev/mtd1 of=%s/bootargs.bin" % self.TMPDIR)
						self.commands.append("dd if=/dev/mtd1 of=%s/bootargs.bin" % self.MAINDEST2)
						self.commands.append('echo "' + _("Create:") + " baseparam dump" + '"')
						self.commands.append("dd if=/dev/mtd2 of=%s/baseparam.bin" % self.TMPDIR)
						self.commands.append('echo "' + _("Create:") + " pq_param dump" + '"')
						self.commands.append("dd if=/dev/mtd3 of=%s/pq_param.bin" % self.TMPDIR)
						self.commands.append('echo "' + _("Create:") + " logo dump" + '"')
						self.commands.append("dd if=/dev/mtd4 of=%s/logo.bin" % self.TMPDIR)
				else:
					self.MKUBIFS_ARGS = "-m 2048 -e 126976 -c 4096 -F"
					self.UBINIZE_ARGS = "-m 2048 -p 128KiB"
					self.commands.append("touch %s/root.ubi" % self.TMPDIR)
					self.commands.append("mkfs.ubifs -r %s/root -o %s/root.ubi %s" % (self.TMPMOUNTDIR, self.TMPDIR, self.MKUBIFS_ARGS))
					self.commands.append("ubinize -o %s/rootfs.ubifs %s %s/ubinize.cfg" % (self.TMPDIR, self.UBINIZE_ARGS, self.TMPDIR))
			else:
				print("[ImageManager] Stage2: TAR.BZIP Detected.")
				self.ROOTFSTYPE = "tar.bz2"
				if SystemInfo["canMultiBoot"]:
					self.commands.append("mount /dev/%s %s/root" % (self.MTDROOTFS, self.TMPMOUNTDIR))
				else:
					self.commands.append("mount --bind / %s/root" % self.TMPMOUNTDIR)
				if SystemInfo["canMultiBoot"] and getCurrentImage() == 0:
					self.commands.append("/bin/tar -jcf %s/rootfs.tar.bz2 -C %s/root --exclude ./var/nmbd --exclude ./.resizerootfs --exclude ./.resize-rootfs --exclude ./.resize-linuxrootfs --exclude ./.resize-userdata --exclude ./var/lib/samba/private/msg.sock ." % (self.TMPDIR, self.TMPMOUNTDIR))
				elif SystemInfo["HasRootSubdir"]:
					self.commands.append("/bin/tar -jcf %s/rootfs.tar.bz2 -C %s/root/%s --exclude ./var/nmbd --exclude ./.resizerootfs --exclude ./.resize-rootfs --exclude ./.resize-linuxrootfs --exclude ./.resize-userdata --exclude ./var/lib/samba/private/msg.sock ." % (self.TMPDIR, self.TMPMOUNTDIR, self.ROOTFSSUBDIR))
				else:
					self.commands.append("/bin/tar -jcf %s/rootfs.tar.bz2 -C %s/root --exclude ./var/nmbd --exclude ./.resizerootfs --exclude ./.resize-rootfs --exclude ./.resize-linuxrootfs --exclude ./.resize-userdata --exclude ./var/lib/samba/private/msg.sock ." % (self.TMPDIR, self.TMPMOUNTDIR))
				if getMachineBuild() == "gb7252" or MODEL == "gbx34k":
					self.commands.append("dd if=/dev/mmcblk0p1 of=%s/boot.bin" % self.TMPDIR)
					self.commands.append("dd if=/dev/mmcblk0p3 of=%s/rescue.bin" % self.TMPDIR)
					print("[ImageManager] Stage2: Create: boot dump boot.bin:", self.MODEL)
					print("[ImageManager] Stage2: Create: rescue dump rescue.bin:", self.MODEL)
			print("[ImageManager] ROOTFSTYPE:", self.ROOTFSTYPE)
			self.Console.eBatch(self.commands, self.Stage2Complete, debug=False)
		except Exception as err:
			print("[ImageManager] doBackup2 Error: %s" % err)
			if path.exists(self.TMPMOUNTDIR) and path.exists(self.MAINDESTROOT) and path.exists(self.TMPDIR) and not path.ismount(TMPMOUNTDIR + "/root"):
				rmtree(self.TMPMOUNTDIR), rmtree(self.TMPDIR), rmtree(self.MAINDESTROOT)
			if self.errorCallback:
				self.errorCallback(err)
			return self.session.openWithCallback(self.close, MessageBox, "%s" % err, MessageBox.TYPE_ERROR, timeout=10)

	def Stage2Complete(self, extra_args=None):
		if len(self.Console.appContainers) == 0:
			self.Stage2Completed = True
			print("[ImageManager] Stage2: Complete.")

	def doBackup3(self):
		print("[ImageManager] Stage3: Making eMMC Image.")
		self.commandMB = []
		SEEK_CONT = int((getFolderSize(self.TMPMOUNTDIR) / 1024) + 100000)
		try:
			if self.EMMCIMG == "disk.img":
				print("[ImageManager] %s: EMMC Detected." % MODEL)  # boxes with multiple eMMC partitions in class
				EMMC_IMAGE = "%s/%s" % (self.TMPDIR, self.EMMCIMG)
				BLOCK_SIZE = 512
				BLOCK_SECTOR = 2
				IMAGE_ROOTFS_ALIGNMENT = 1024
				BOOT_PARTITION_SIZE = 3072
				KERNEL_PARTITION_SIZE = 8192
				ROOTFS_PARTITION_SIZE = 1048576
				EMMC_IMAGE_SIZE = 3817472
				KERNEL_PARTITION_OFFSET = int(IMAGE_ROOTFS_ALIGNMENT) + int(BOOT_PARTITION_SIZE)
				ROOTFS_PARTITION_OFFSET = int(KERNEL_PARTITION_OFFSET) + int(KERNEL_PARTITION_SIZE)
				SECOND_KERNEL_PARTITION_OFFSET = int(ROOTFS_PARTITION_OFFSET) + int(ROOTFS_PARTITION_SIZE)
				THIRD_KERNEL_PARTITION_OFFSET = int(SECOND_KERNEL_PARTITION_OFFSET) + int(KERNEL_PARTITION_SIZE)
				FOURTH_KERNEL_PARTITION_OFFSET = int(THIRD_KERNEL_PARTITION_OFFSET) + int(KERNEL_PARTITION_SIZE)
				MULTI_ROOTFS_PARTITION_OFFSET = int(FOURTH_KERNEL_PARTITION_OFFSET) + int(KERNEL_PARTITION_SIZE)
				EMMC_IMAGE_SEEK = int(EMMC_IMAGE_SIZE) * int(BLOCK_SECTOR)
				self.commandMB.append("dd if=/dev/zero of=%s bs=%s count=0 seek=%s" % (EMMC_IMAGE, BLOCK_SIZE, EMMC_IMAGE_SEEK))
				self.commandMB.append("parted -s %s mklabel gpt" % EMMC_IMAGE)
				PARTED_END_BOOT = int(IMAGE_ROOTFS_ALIGNMENT) + int(BOOT_PARTITION_SIZE)
				self.commandMB.append("parted -s %s unit KiB mkpart boot fat16 %s %s" % (EMMC_IMAGE, IMAGE_ROOTFS_ALIGNMENT, PARTED_END_BOOT))
				PARTED_END_KERNEL1 = int(KERNEL_PARTITION_OFFSET) + int(KERNEL_PARTITION_SIZE)
				self.commandMB.append("parted -s %s unit KiB mkpart linuxkernel %s %s" % (EMMC_IMAGE, KERNEL_PARTITION_OFFSET, PARTED_END_KERNEL1))
				PARTED_END_ROOTFS1 = int(ROOTFS_PARTITION_OFFSET) + int(ROOTFS_PARTITION_SIZE)
				self.commandMB.append("parted -s %s unit KiB mkpart linuxrootfs ext4 %s %s" % (EMMC_IMAGE, ROOTFS_PARTITION_OFFSET, PARTED_END_ROOTFS1))
				PARTED_END_KERNEL2 = int(SECOND_KERNEL_PARTITION_OFFSET) + int(KERNEL_PARTITION_SIZE)
				self.commandMB.append("parted -s %s unit KiB mkpart linuxkernel2 %s %s" % (EMMC_IMAGE, SECOND_KERNEL_PARTITION_OFFSET, PARTED_END_KERNEL2))
				PARTED_END_KERNEL3 = int(THIRD_KERNEL_PARTITION_OFFSET) + int(KERNEL_PARTITION_SIZE)
				self.commandMB.append("parted -s %s unit KiB mkpart linuxkernel3 %s %s" % (EMMC_IMAGE, THIRD_KERNEL_PARTITION_OFFSET, PARTED_END_KERNEL3))
				PARTED_END_KERNEL4 = int(FOURTH_KERNEL_PARTITION_OFFSET) + int(KERNEL_PARTITION_SIZE)
				self.commandMB.append("parted -s %s unit KiB mkpart linuxkernel4 %s %s" % (EMMC_IMAGE, FOURTH_KERNEL_PARTITION_OFFSET, PARTED_END_KERNEL4))
				try:
					with open("/proc/swaps", "r") as rd:
						if "mmcblk0p7" in rd.read():
							SWAP_PARTITION_OFFSET = int(FOURTH_KERNEL_PARTITION_OFFSET) + int(KERNEL_PARTITION_SIZE)
							SWAP_PARTITION_SIZE = int(262144)
							MULTI_ROOTFS_PARTITION_OFFSET = int(SWAP_PARTITION_OFFSET) + int(SWAP_PARTITION_SIZE)
							self.commandMB.append("parted -s %s unit KiB mkpart swap linux-swap %s %s" % (EMMC_IMAGE, SWAP_PARTITION_OFFSET, SWAP_PARTITION_OFFSET + SWAP_PARTITION_SIZE))
							self.commandMB.append("parted -s %s unit KiB mkpart userdata ext4 %s 100%%" % (EMMC_IMAGE, MULTI_ROOTFS_PARTITION_OFFSET))
						else:
							self.commandMB.append("parted -s %s unit KiB mkpart userdata ext4 %s 100%%" % (EMMC_IMAGE, MULTI_ROOTFS_PARTITION_OFFSET))
				except Exception:
					self.commandMB.append("parted -s %s unit KiB mkpart userdata ext4 %s 100%%" % (EMMC_IMAGE, MULTI_ROOTFS_PARTITION_OFFSET))

				BOOT_IMAGE_SEEK = int(IMAGE_ROOTFS_ALIGNMENT) * int(BLOCK_SECTOR)
				self.commandMB.append("dd if=%s of=%s seek=%s" % (self.MTDBOOT, EMMC_IMAGE, BOOT_IMAGE_SEEK))
				KERNEL_IMAGE_SEEK = int(KERNEL_PARTITION_OFFSET) * int(BLOCK_SECTOR)
				self.commandMB.append("dd if=/dev/%s of=%s seek=%s" % (self.MTDKERNEL, EMMC_IMAGE, KERNEL_IMAGE_SEEK))
				ROOTFS_IMAGE_SEEK = int(ROOTFS_PARTITION_OFFSET) * int(BLOCK_SECTOR)
				self.commandMB.append("dd if=/dev/%s of=%s seek=%s " % (self.MTDROOTFS, EMMC_IMAGE, ROOTFS_IMAGE_SEEK))
				self.Console.eBatch(self.commandMB, self.Stage3Complete, debug=False)

			elif self.EMMCIMG == "emmc.img":
				print("[ImageManager] %s: EMMC Detected." % MODEL)  # boxes with multiple eMMC partitions in class
				EMMC = "rootfs.ext4"
				EMMC_IMAGE = "%s/%s" % (self.TMPDIR, EMMC)
				IMAGE_ROOTFS_ALIGNMENT = 1024
				BOOT_PARTITION_SIZE = 3072
				KERNEL_PARTITION_SIZE = 8192
				ROOTFS_PARTITION_SIZE = 1898496  # work backup partitions with 848576
				EMMC_IMAGE_SIZE = 7634944  # work backup partitions with 3817472
				# ######################################ENUMERATE PARTITIONS ###########################################################
				KERNEL1_PARTITION_OFFSET = int(IMAGE_ROOTFS_ALIGNMENT) + int(BOOT_PARTITION_SIZE)
				ROOTFS1_PARTITION_OFFSET = int(KERNEL1_PARTITION_OFFSET) + int(KERNEL_PARTITION_SIZE)
				KERNEL2_PARTITION_OFFSET = int(ROOTFS1_PARTITION_OFFSET) + int(ROOTFS_PARTITION_SIZE)
				ROOTFS2_PARTITION_OFFSET = int(KERNEL2_PARTITION_OFFSET) + int(KERNEL_PARTITION_SIZE)
				KERNEL3_PARTITION_OFFSET = int(ROOTFS2_PARTITION_OFFSET) + int(ROOTFS_PARTITION_SIZE)
				ROOTFS3_PARTITION_OFFSET = int(KERNEL3_PARTITION_OFFSET) + int(KERNEL_PARTITION_SIZE)
				KERNEL4_PARTITION_OFFSET = int(ROOTFS3_PARTITION_OFFSET) + int(ROOTFS_PARTITION_SIZE)
				ROOTFS4_PARTITION_OFFSET = int(KERNEL4_PARTITION_OFFSET) + int(KERNEL_PARTITION_SIZE)
				# ######################################CREATE PARTITIONS 4 SLOTS#######################################################
				EMMC_IMAGE_SEEK = int(EMMC_IMAGE_SIZE) * int(IMAGE_ROOTFS_ALIGNMENT)
				self.commandMB.append("dd if=/dev/zero of=%s bs=1 count=0 seek=%s" % (EMMC_IMAGE, EMMC_IMAGE_SEEK))
				self.commandMB.append("parted -s %s mklabel gpt" % EMMC_IMAGE)
				PARTED_END_BOOT = int(IMAGE_ROOTFS_ALIGNMENT) + int(BOOT_PARTITION_SIZE)
				self.commandMB.append("parted -s %s unit KiB mkpart boot fat16 %s %s" % (EMMC_IMAGE, IMAGE_ROOTFS_ALIGNMENT, PARTED_END_BOOT))
				self.commandMB.append("parted -s %s set 1 boot on" % EMMC_IMAGE)
				PARTED_END_KERNEL1 = int(KERNEL1_PARTITION_OFFSET) + int(KERNEL_PARTITION_SIZE)
				self.commandMB.append("parted -s %s unit KiB mkpart kernel1 %s %s" % (EMMC_IMAGE, KERNEL1_PARTITION_OFFSET, PARTED_END_KERNEL1))
				PARTED_END_ROOTFS1 = int(ROOTFS1_PARTITION_OFFSET) + int(ROOTFS_PARTITION_SIZE)
				self.commandMB.append("parted -s %s unit KiB mkpart rootfs1 ext4 %s %s" % (EMMC_IMAGE, ROOTFS1_PARTITION_OFFSET, PARTED_END_ROOTFS1))
				PARTED_END_KERNEL2 = int(KERNEL2_PARTITION_OFFSET) + int(KERNEL_PARTITION_SIZE)
				self.commandMB.append("parted -s %s unit KiB mkpart kernel2 %s %s" % (EMMC_IMAGE, KERNEL2_PARTITION_OFFSET, PARTED_END_KERNEL2))
				PARTED_END_ROOTFS2 = int(ROOTFS2_PARTITION_OFFSET) + int(ROOTFS_PARTITION_SIZE)
				self.commandMB.append("parted -s %s unit KiB mkpart rootfs2 ext4 %s %s" % (EMMC_IMAGE, ROOTFS2_PARTITION_OFFSET, PARTED_END_ROOTFS2))
				PARTED_END_KERNEL3 = int(KERNEL3_PARTITION_OFFSET) + int(KERNEL_PARTITION_SIZE)
				self.commandMB.append("parted -s %s unit KiB mkpart kernel3 %s %s" % (EMMC_IMAGE, KERNEL3_PARTITION_OFFSET, PARTED_END_KERNEL3))
				PARTED_END_ROOTFS3 = int(ROOTFS3_PARTITION_OFFSET) + int(ROOTFS_PARTITION_SIZE)
				self.commandMB.append("parted -s %s unit KiB mkpart rootfs3 ext4 %s %s" % (EMMC_IMAGE, ROOTFS3_PARTITION_OFFSET, PARTED_END_ROOTFS3))
				PARTED_END_KERNEL4 = int(KERNEL4_PARTITION_OFFSET) + int(KERNEL_PARTITION_SIZE)
				self.commandMB.append("parted -s %s unit KiB mkpart kernel4 %s %s" % (EMMC_IMAGE, KERNEL4_PARTITION_OFFSET, PARTED_END_KERNEL4))
				PARTED_END_ROOTFS4 = int(ROOTFS4_PARTITION_OFFSET) + int(ROOTFS_PARTITION_SIZE)
				self.commandMB.append("parted -s %s unit KiB mkpart rootfs4 ext4 %s %s" % (EMMC_IMAGE, ROOTFS4_PARTITION_OFFSET, PARTED_END_ROOTFS4))
				# ######################################CREATE FULL BACKUP IMAGE SLOT 1 WITH BOOT + KERNEL + ROOTFS IMAGE###############
				BOOT_IMAGE_BS = int(IMAGE_ROOTFS_ALIGNMENT) * int(IMAGE_ROOTFS_ALIGNMENT)
				self.commandMB.append("dd conv=notrunc if=%s of=%s seek=1 bs=%s" % (self.MTDBOOT, EMMC_IMAGE, BOOT_IMAGE_BS))
				KERNEL = int(BOOT_PARTITION_SIZE) * int(IMAGE_ROOTFS_ALIGNMENT)
				KERNEL_BS = BOOT_IMAGE_BS + KERNEL
				self.commandMB.append("dd conv=notrunc if=/dev/%s of=%s seek=1 bs=%s" % (self.MTDKERNEL, EMMC_IMAGE, KERNEL_BS))
				ROOTFS_IMAGE = int(KERNEL_PARTITION_SIZE) * int(IMAGE_ROOTFS_ALIGNMENT)
				ROOTFS_IMAGE_BS = KERNEL_BS + ROOTFS_IMAGE
				# self.commandMB.append("dd if=/dev/%s of=%s seek=1 bs=%s" % (self.MTDROOTFS, EMMC_IMAGE, ROOTFS_IMAGE_BS)) # deactive (not work image emmc.img).
				self.Console.eBatch(self.commandMB, self.Stage3Complete, debug=False)
			elif self.EMMCIMG == "usb_update.bin" and self.ROOTFSSUBDIR.endswith("1"):  # create slot 1 recovery backup image and empty partitions for the remaining slots.
				print("[ImageManager] %s: Making emmc_partitions.xml" % MODEL)
				with open("%s/emmc_partitions.xml" % self.TMPDIR, "w") as f:
					f.write('<?xml version="1.0" encoding="GB2312" ?>\n')
					f.write('<Partition_Info>\n')
					f.write('<Part Sel="1" PartitionName="fastboot" FlashType="emmc" FileSystem="none" Start="0" Length="1M" SelectFile="fastboot.bin"/>\n')
					f.write('<Part Sel="1" PartitionName="bootargs" FlashType="emmc" FileSystem="none" Start="1M" Length="1M" SelectFile="bootargs.bin"/>\n')
					f.write('<Part Sel="1" PartitionName="bootoptions" FlashType="emmc" FileSystem="none" Start="2M" Length="1M" SelectFile="boot.img"/>\n')
					f.write('<Part Sel="1" PartitionName="baseparam" FlashType="emmc" FileSystem="none" Start="3M" Length="3M" SelectFile="baseparam.img"/>\n')
					f.write('<Part Sel="1" PartitionName="pqparam" FlashType="emmc" FileSystem="none" Start="6M" Length="4M" SelectFile="pq_param.bin"/>\n')
					f.write('<Part Sel="1" PartitionName="logo" FlashType="emmc" FileSystem="none" Start="10M" Length="4M" SelectFile="logo.img"/>\n')
					f.write('<Part Sel="1" PartitionName="deviceinfo" FlashType="emmc" FileSystem="none" Start="14M" Length="4M" SelectFile="deviceinfo.bin"/>\n')
					f.write('<Part Sel="1" PartitionName="loader" FlashType="emmc" FileSystem="none" Start="26M" Length="32M" SelectFile="apploader.bin"/>\n')
					f.write('<Part Sel="1" PartitionName="kernel" FlashType="emmc" FileSystem="none" Start="66M" Length="16M" SelectFile="kernel.bin"/>\n')
					f.write('<Part Sel="1" PartitionName="rootfs" FlashType="emmc" FileSystem="ext3/4" Start="130M" Length="7000M" SelectFile="rootfs.ext4"/>\n')
					f.write('</Partition_Info>\n')
					f.close()
				print('[ImageManager] %s: Executing partitions for %s' % (MODEL, self.EMMCIMG))
				self.commandMB.append('echo "Create: fastboot dump"')
				self.commandMB.append("dd if=/dev/mmcblk0p1 of=%s/fastboot.bin" % self.TMPDIR)
				self.commandMB.append('echo "Create: bootargs dump"')
				self.commandMB.append("dd if=/dev/mmcblk0p2 of=%s/bootargs.bin" % self.TMPDIR)
				self.commandMB.append('echo "Create: boot dump"')
				self.commandMB.append("dd if=/dev/mmcblk0p3 of=%s/boot.img" % self.TMPDIR)
				self.commandMB.append('echo "Create: baseparam.dump"')
				self.commandMB.append("dd if=/dev/mmcblk0p4 of=%s/baseparam.img" % self.TMPDIR)
				self.commandMB.append('echo "Create: pq_param dump"')
				self.commandMB.append("dd if=/dev/mmcblk0p5 of=%s/pq_param.bin" % self.TMPDIR)
				self.commandMB.append('echo "Create: logo dump"')
				self.commandMB.append("dd if=/dev/mmcblk0p6 of=%s/logo.img" % self.TMPDIR)
				self.commandMB.append('echo "Create: deviceinfo dump"')
				self.commandMB.append("dd if=/dev/mmcblk0p7 of=%s/deviceinfo.bin" % self.TMPDIR)
				self.commandMB.append('echo "Create: apploader dump"')
				self.commandMB.append("dd if=/dev/mmcblk0p10 of=%s/apploader.bin" % self.TMPDIR)
				self.commandMB.append('echo "Pickup previous created: kernel dump"')
				self.commandMB.append('echo "Create: rootfs dump"')
				self.commandMB.append("mkdir -p %s/userdata" % self.TMPDIR)
				for linuxrootfs in range(1, 5):
					self.commandMB.append("mkdir -p %s/userdata/linuxrootfs%d" % (self.TMPDIR, linuxrootfs))
				self.commandMB.append("mount %s/root/linuxrootfs1 %s/userdata/linuxrootfs1" % (self.TMPMOUNTDIR, self.TMPDIR))
				self.commandMB.append("dd if=/dev/zero of=%s/rootfs.ext4 seek=%s count=60 bs=1024" % (self.TMPDIR, SEEK_CONT))
				self.commandMB.append("mkfs.ext4 -F -i 4096 %s/rootfs.ext4 -d %s/userdata" % (self.TMPDIR, self.TMPDIR))
				self.commandMB.append("umount %s/userdata/linuxrootfs1" % (self.TMPDIR))
				self.commandMB.append('echo "Creating recovery emmc %s image for %s"' % (self.EMMCIMG, MODEL))
				self.commandMB.append('mkupdate -s 00000003-00000001-01010101 -f %s/emmc_partitions.xml -d %s/%s' % (self.TMPDIR, self.TMPDIR, self.EMMCIMG))
				self.Console.eBatch(self.commandMB, self.Stage3Complete, debug=False)
			else:
				self.Stage3Completed = True
				print("[ImageManager] Stage 3 bypassed: Complete.")
		except Exception as err:
			print("[ImageManager] doBackup3 Error: %s" % err)
			if path.exists(self.TMPMOUNTDIR) and path.exists(self.MAINDESTROOT) and path.exists(self.TMPDIR) and not path.ismount(TMPMOUNTDIR + "/root"):
				rmtree(self.TMPMOUNTDIR), rmtree(self.TMPDIR), rmtree(self.MAINDESTROOT)
			if self.errorCallback:
				self.errorCallback(err)
			return self.session.openWithCallback(self.close, MessageBox, "%s" % err, MessageBox.TYPE_ERROR, timeout=10)

	def Stage3Complete(self, extra_args=None):
		self.Stage3Completed = True
		print("[ImageManager] Stage3: Complete.")

	def doBackup4(self):
		print("[ImageManager] Stage4: Unmounting and removing tmp system")
		try:
			if path.exists(self.TMPMOUNTDIR + "/root") and path.ismount(self.TMPMOUNTDIR + "/root"):
				self.command = "umount " + self.TMPMOUNTDIR + "/root && rm -rf " + self.TMPMOUNTDIR
				self.Console.ePopen(self.command, self.Stage4Complete)
			else:
				if path.exists(self.TMPMOUNTDIR):
					rmtree(self.TMPMOUNTDIR)
				self.Stage4Complete("pass", 0)
		except Exception as err:
			print("[ImageManager] doBackup4 umount TMPMOUNTDIR root Error: %s" % err)

	def Stage4Complete(self, result, retval, extra_args=None):
		if retval == 0:
			self.Stage4Completed = True
			print("[ImageManager] Stage4: Complete.")

	def doBackup5(self):
		print("[ImageManager] Stage5: Moving from work to backup folders")
		try:
			if self.EMMCIMG == "emmc.img" or self.EMMCIMG == "disk.img" and path.exists("%s/%s" % (self.TMPDIR, self.EMMCIMG)):
				if path.exists("%s/%s" % (self.TMPDIR, self.EMMCIMG)):
					move("%s/%s" % (self.TMPDIR, self.EMMCIMG), "%s%s" % (self.MAINDEST, self.EMMCIMG))
				if path.exists("%s/rootfs.ext4" % self.TMPDIR) and not MODEL.startswith("osmio4k"):
					move("%s/rootfs.ext4" % self.TMPDIR, "%s%s" % (self.MAINDEST, self.EMMCIMG))
			if self.EMMCIMG == "usb_update.bin":
				if path.exists("%s/%s" % (self.TMPDIR, self.EMMCIMG)):
					move("%s/%s" % (self.TMPDIR, self.EMMCIMG), "%s/%s" % (self.MAINDESTROOT, self.EMMCIMG))
				if path.exists("%s/fastboot.bin" % self.TMPDIR):
					move("%s/fastboot.bin" % self.TMPDIR, "%s/fastboot.bin" % self.MAINDESTROOT)
				if path.exists("%s/bootargs.bin" % self.TMPDIR):
					move("%s/bootargs.bin" % self.TMPDIR, "%s/bootargs.bin" % self.MAINDESTROOT)
				if path.exists("%s/apploader.bin" % self.TMPDIR):
					move("%s/apploader.bin" % self.TMPDIR, "%s/apploader.bin" % self.MAINDESTROOT)

			if path.exists("%s/kernel.bin" % self.TMPDIR):
				move("%s/kernel.bin" % self.TMPDIR, "%s/%s" % (self.MAINDEST, self.KERNELFILE))
			elif path.exists("%s/vmlinux.bin" % self.TMPDIR):
				move("%s/vmlinux.bin" % self.TMPDIR, "%s/%s" % (self.MAINDEST, self.KERNELFILE))
			else:
				move("%s/vmlinux.gz" % self.TMPDIR, "%s/%s" % (self.MAINDEST, self.KERNELFILE))

			if MODEL in ("h9", "i55plus"):
				system("mv %s/fastboot.bin %s/fastboot.bin" % (self.TMPDIR, self.MAINDEST))
				system("mv %s/bootargs.bin %s/bootargs.bin" % (self.TMPDIR, self.MAINDEST))
				system("mv %s/pq_param.bin %s/pq_param.bin" % (self.TMPDIR, self.MAINDEST))
				system("mv %s/baseparam.bin %s/baseparam.bin" % (self.TMPDIR, self.MAINDEST))
				system("mv %s/logo.bin %s/logo.bin" % (self.TMPDIR, self.MAINDEST))
				system("cp -f /usr/share/fastboot.bin %s/fastboot.bin" % self.MAINDEST2)
				system("cp -f /usr/share/bootargs.bin %s/bootargs.bin" % self.MAINDEST2)
				with open("/proc/cmdline", "r") as z:
					if SystemInfo["HasMMC"] and "root=/dev/mmcblk0p1" in z.read():
						move("%s/rootfs.tar.bz2" % self.TMPDIR, "%s/rootfs.tar.bz2" % self.MAINDEST)
					else:
						move("%s/rootfs.%s" % (self.TMPDIR, self.ROOTFSTYPE), "%s/%s" % (self.MAINDEST, self.ROOTFSFILE))
			else:
				move("%s/rootfs.%s" % (self.TMPDIR, self.ROOTFSTYPE), "%s/%s" % (self.MAINDEST, self.ROOTFSFILE))

			if getMachineBuild() == "gb7252" or MODEL == "gbx34k":
				move("%s/%s" % (self.TMPDIR, self.GB4Kbin), "%s/%s" % (self.MAINDEST, self.GB4Kbin))
				move("%s/%s" % (self.TMPDIR, self.GB4Krescue), "%s/%s" % (self.MAINDEST, self.GB4Krescue))
				system("cp -f /usr/share/gpt.bin %s/gpt.bin" % self.MAINDEST)
				print("[ImageManager] Stage5: Create: gpt.bin:", self.MODEL)

			with open(self.MAINDEST + "/imageversion", "w") as fileout:
				line = defaultprefix + "-" + backupimage + "-" + MODEL + "-" + self.BackupDate
				fileout.write(line)
				fileout.close()
			if BRAND == "Vu+":
				if MODEL in ("vuzero4k, vuuno4k"):
					with open(self.MAINDEST + "/force.update", "w") as fileout:
						line = "This file forces the update."
						fileout.write(line)
						fileout.close()
				else:
					with open(self.MAINDEST + "/reboot.update", "w") as fileout:
						line = "This file forces a reboot after the update."
						fileout.write(line)
						fileout.close()
			elif BRAND in ("xtrend", "GigaBlue", "octagon", "odin", "xp", "INI", "Edision"):
				with open(self.MAINDEST + "/noforce", "w") as fileout:
					line = "rename this file to 'force' to force an update without confirmation"
					fileout.write(line)
					fileout.close()
				if path.exists("/usr/lib/enigma2/python/Plugins/SystemPlugins/Vision/burn.bat"):
					copy("/usr/lib/enigma2/python/Plugins/SystemPlugins/Vision/burn.bat", self.MAINDESTROOT + "/burn.bat")
				if SystemInfo["HiSilicon"] and self.KERN == "mmc":
					with open(self.MAINDEST + "/SDAbackup", "w") as fileout:
						line = "%s indicate type of backup %s" % (MODEL, self.KERN)
						fileout.write(line)
						fileout.close()
				if self.EMMCIMG in ("emmc.img", "disk.img", "usb_update.bin"):
					if self.EMMCIMG == "usb_update.bin":
						with open(self.MAINDEST2 + "/imageversion", "w") as fileout:
							line = defaultprefix + "-" + backupimage + "-" + MODEL + "-" + self.BackupDate
							fileout.write(line)
							fileout.close()
					if self.EMMCIMG in ("emmc.img", "disk.img") and not MODEL.startswith("osmio4k") or self.EMMCIMG == "usb_update.bin" and self.ROOTFSSUBDIR.endswith("1"):
						self.session.open(MessageBox, _("Creating image online flash for ofgwrite and recovery eMMC."), MessageBox.TYPE_INFO, timeout=10)
					else:
						self.session.open(MessageBox, _("Creating image online flash for ofgwrite."), MessageBox.TYPE_INFO, timeout=10)
			elif SystemInfo["HasRootSubdir"]:
				with open(self.MAINDEST + "/force_%s_READ.ME" % MODEL, "w") as fileout:
					line1 = "Rename the unforce_%s.txt to force_%s.txt and move it to the root of your usb-stick" % (MODEL, MODEL)
					line2 = "When you enter the recovery menu then it will force the image to be installed in the linux selection"
					fileout.write(line1)
					fileout.write(line2)
					fileout.close()
				with open(self.MAINDEST2 + "/unforce_%s.txt" % MODEL, "w") as fileout:
					line1 = "rename this unforce_%s.txt to force_%s.txt to force an update without confirmation" % (MODEL, MODEL)
					fileout.write(line1)
					fileout.close()
			print("[ImageManager] Stage5: Removing Swap.")
			if path.exists(self.swapdevice + config.imagemanager.folderprefix.value + "-" + imagetype + "-swapfile_backup"):
				system("swapoff " + self.swapdevice + config.imagemanager.folderprefix.value + "-" + imagetype + "-swapfile_backup")
				remove(self.swapdevice + config.imagemanager.folderprefix.value + "-" + imagetype + "-swapfile_backup")
			if path.exists(self.TMPDIR):
				rmtree(self.TMPDIR)
			if (path.exists(self.MAINDEST + "/" + self.ROOTFSFILE) and path.exists(self.MAINDEST + "/" + self.KERNELFILE)) or (MODEL in ("h9", "i55plus") and "root=/dev/mmcblk0p1" in z):
				for root, dirs, files in walk(self.MAINDEST):
					for momo in dirs:
						chmod(path.join(root, momo), 0o644)
					for momo in files:
						chmod(path.join(root, momo), 0o644)
				print("[ImageManager] Stage 5: Image created in " + self.MAINDESTROOT)
				self.Stage5Complete()
			else:
				print("[ImageManager] Stage5: Image creation failed - e. g. wrong backup destination or no space left on backup device")
				self.BackupComplete()
		except Exception as err:
			print("[ImageManager] doBackup5 Error: %s" % err)
			if path.exists(self.MAINDESTROOT) and path.exists(self.TMPDIR) and not path.ismount(TMPMOUNTDIR + "/root"):
				rmtree(self.TMPDIR), rmtree(self.MAINDESTROOT)
			if self.errorCallback:
				self.errorCallback(err)
			return self.session.openWithCallback(self.close, MessageBox, "%s" % err, MessageBox.TYPE_ERROR, timeout=10)

	def Stage5Complete(self):
		self.Stage5Completed = True
		print("[ImageManager] Stage5: Complete.")

	def doBackup6(self):
		zipfolder = path.split(self.MAINDESTROOT)
		try:
			if self.EMMCIMG in ("emmc.img", "disk.img", "usb_update.bin"):
				if self.EMMCIMG in ("emmc.img", "disk.img") and not MODEL.startswith("osmio4k") or self.EMMCIMG == "usb_update.bin" and self.ROOTFSSUBDIR.endswith("1"):
					self.commandMB.append("7za a -r -bt -bd %s%s-%s-%s-%s_recovery_emmc.zip %s/*" % (self.BackupDirectory, self.IMAGEDISTRO, self.DISTROBUILD, self.MODEL, self.BackupDate, self.MAINDESTROOT))
				else:
					self.commandMB.append("7za a -r -bt -bd %s%s-%s-%s-%s%s_mmc.zip %s/*" % (self.BackupDirectory, self.IMAGEDISTRO, self.DISTROBUILD, self.MODEL, self.BackupDate, self.VuSlot0, self.MAINDESTROOT))
					self.commandMB.append("sync")
			else:
				self.commandMB.append("cd " + self.MAINDESTROOT + " && zip -r " + self.MAINDESTROOT + "_usb.zip *")
		except Exception as err:
			print("[ImageManager] doBackup6 Error: %s" % err)
			self.commandMB.append("rm -rf " + self.MAINDESTROOT)
		self.commandMB.append("rm -rf " + self.MAINDESTROOT)
		self.Console.eBatch(self.commandMB, self.Stage6Complete, debug=True)

	def Stage6Complete(self, answer=None):
		self.Stage6Completed = True
		print("[ImageManager] Stage6: Complete.")

	def BackupComplete(self, answer=None):
		#    trim the number of backups kept...
		import fnmatch
		try:
			if config.imagemanager.number_to_keep.value > 0 and path.exists(self.BackupDirectory):  # !?!
				images = listdir(self.BackupDirectory)
				patt = config.imagemanager.folderprefix.value + "-*.zip"
				emlist = []
				for fil in images:
					if fnmatch.fnmatchcase(fil, patt):
						emlist.append(fil)
				# sort by oldest first...
				emlist.sort(key=lambda fil: path.getmtime(self.BackupDirectory + fil))
				# ...then, if we have too many, remove the <n> newest from the end
				# and delete what is left
				if len(emlist) > config.imagemanager.number_to_keep.value:
					emlist = emlist[0:len(emlist) - config.imagemanager.number_to_keep.value]
					for fil in emlist:
						if path.exists(self.BackupDirectory + fil):
							remove(self.BackupDirectory + fil)
		except Exception:
			pass
		if config.imagemanager.schedule.value:
			atLeast = 60
			autoImageManagerTimer.backupupdate(atLeast)
		else:
			autoImageManagerTimer.backupstop()


class ImageManagerDownload(Screen):
	skin = """
	<screen name="VISIONImageManager" position="center,center" size="1000,500">
		<ePixmap pixmap="buttons/red.png" position="0,0" size="140,40" alphaTest="blend" />
		<ePixmap pixmap="buttons/green.png" position="140,0" size="140,40" alphaTest="blend" />
		<ePixmap pixmap="buttons/yellow.png" position="280,0" size="140,40" alphaTest="blend" />
		<ePixmap pixmap="buttons/blue.png" position="420,0" size="140,40" alphaTest="blend" />
		<widget name="key_red" position="0,0" zPosition="1" size="140,40" font="Regular;20" horizontalAlignment="center" verticalAlignment="center" backgroundColor="#9f1313" transparent="1" />
		<widget name="key_green" position="140,0" zPosition="1" size="140,40" font="Regular;20" horizontalAlignment="center" verticalAlignment="center" backgroundColor="#1f771f" transparent="1" />
		<widget name="key_yellow" position="280,0" zPosition="1" size="140,40" font="Regular;20" horizontalAlignment="center" verticalAlignment="center" backgroundColor="#a08500" transparent="1" />
		<widget name="key_blue" position="420,0" zPosition="1" size="140,40" font="Regular;20" horizontalAlignment="center" verticalAlignment="center" backgroundColor="#18188b" transparent="1" />
		<widget name="lab6" position="0,50" size="560,50" font="Regular; 18" zPosition="2" transparent="0" horizontalAlignment="center"/>
		<widget name="list" position="10,105" size="980,480" scrollbarMode="showOnDemand" />
		<applet type="onLayoutFinish">
			self["list"].instance.setItemHeight(25)
		</applet>
	</screen>"""

	def __init__(self, session, BackupDirectory, ConfigObj):
		Screen.__init__(self, session)
		self.setTitle(_("%s downloads") % {config.imagemanager.imagefeed_OV: "Open Vision", config.imagemanager.imagefeed_ATV: "OpenATV", config.imagemanager.imagefeed_PLi: "OpenPLi", config.imagemanager.imagefeed_ViX: "OpenViX", config.imagemanager.imagefeed_OBH: "OpenBh"}.get(ConfigObj, ''))
		self.ConfigObj = ConfigObj
		self.BackupDirectory = BackupDirectory
		self["lab1"] = StaticText(_("norhap"))
		self["lab2"] = StaticText(_("Report problems to:"))
		self["lab3"] = StaticText(_("telegram @norhap"))
		self["lab4"] = StaticText(_("Sources are available at:"))
		self["lab5"] = StaticText(_("https://github.com/norhap"))
		self["lab6"] = Label(_("Select an image to download:"))
		self["key_red"] = Button(_("Close"))
		self["key_green"] = StaticText("")
		self["ImageDown"] = ActionMap(["OkCancelActions", "ColorActions", "DirectionActions", "KeyboardInputActions", "MenuActions"], {
			"cancel": self.close,
			"red": self.close,
			"green": self.keyDownload,
			"ok": self.keyDownload,
			"up": self.keyUp,
			"down": self.keyDown,
			"upUp": self.doNothing,
			"downUp": self.doNothing,
			"rightUp": self.doNothing,
			"leftUp": self.doNothing,
			"left": self.keyLeft,
			"right": self.keyRight,
			"upRepeated": self.keyUp,
			"downRepeated": self.keyDown,
			"leftRepeated": self.keyUp,
			"rightRepeated": self.keyDown,
			"menu": self.close
		}, -1)
		self.imagesList = {}
		self.setIndex = 0
		self.expanded = []
		self["list"] = ChoiceList(list=[ChoiceEntryComponent("", ((_("No images found on the selected download server...if password check validity")), "Waiter"))])
		self.getImageDistro()

	def getImageDistro(self):
		if config.imagemanager.backuplocation.value != "/" and not path.exists(self.BackupDirectory):
			mkdir(self.BackupDirectory, 0o755)

		if not self.imagesList:
			try:
				urljson = path.join(self.ConfigObj.value, MODEL)
				self.imagesList = dict(json.load(urlopen("%s" % urljson)))
			except Exception:
				print("[ImageManager] no images available for: the '%s' at '%s'" % (MODEL, self.ConfigObj.value))
				return

		if not self.imagesList:  # Nothing has been found on that server so we might as well give up.
			return

		imglist = []  # this is reset on every "ok" key press of an expandable item so it reflects the current state of expandability of that item
		for categorie in sorted(self.imagesList.keys(), reverse=True):
			if categorie in self.expanded:
				imglist.append(ChoiceEntryComponent("expanded", ((str(categorie)), "Expander")))
				for image in sorted(self.imagesList[categorie].keys(), reverse=True):
					imglist.append(ChoiceEntryComponent("verticalline", ((str(self.imagesList[categorie][image]["name"])), str(self.imagesList[categorie][image]["link"]))))
			else:
				# print("[ImageManager] [GetImageDistro] keys: %s" % list(self.imagesList[categorie].keys()))
				for image in list(self.imagesList[categorie].keys()):
					imglist.append(ChoiceEntryComponent("expandable", ((str(categorie)), "Expander")))
					break
		if imglist:
			# print("[ImageManager] [GetImageDistro] imglist: %s" % imglist)
			self["list"].setList(imglist)
			if self.setIndex:
				self["list"].moveToIndex(self.setIndex if self.setIndex < len(list) else len(list) - 1)
				if self["list"].l.getCurrentSelection()[0][1] == "Expander":
					self.setIndex -= 1
					if self.setIndex:
						self["list"].moveToIndex(self.setIndex if self.setIndex < len(list) else len(list) - 1)
				self.setIndex = 0
			self.SelectionChanged()
		else:
			return

	def SelectionChanged(self):
		currentSelected = self["list"].l.getCurrentSelection()
		if currentSelected[0][1] == "Waiter":
			self["key_green"].setText("")
		else:
			if currentSelected[0][1] == "Expander":
				self["key_green"].setText(_("Compress") if currentSelected[0][0] in self.expanded else _("Expand"))
			else:
				self["key_green"].setText(_("DownLoad"))

	def keyLeft(self):
		self["list"].instance.moveSelection(self["list"].instance.pageUp)
		self.SelectionChanged()

	def keyRight(self):
		self["list"].instance.moveSelection(self["list"].instance.pageDown)
		self.SelectionChanged()

	def keyUp(self):
		self["list"].instance.moveSelection(self["list"].instance.moveUp)
		self.SelectionChanged()

	def keyDown(self):
		self["list"].instance.moveSelection(self["list"].instance.moveDown)
		self.SelectionChanged()

	def doNothing(self):
		pass

	def keyDownload(self):
		currentSelected = self["list"].l.getCurrentSelection()
		if currentSelected[0][1] == "Expander":
			if currentSelected[0][0] in self.expanded:
				self.expanded.remove(currentSelected[0][0])
			else:
				self.expanded.append(currentSelected[0][0])
			self.getImageDistro()

		elif currentSelected[0][1] != "Waiter":
			self.sel = currentSelected[0][0]
			if self.sel:
				message = _("Are you sure you want to download this image:\n ") + self.sel
				ybox = self.session.openWithCallback(self.doDownloadX, MessageBox, message, MessageBox.TYPE_YESNO)
				ybox.setTitle(_("Download confirmation"))
			else:
				self.close()

	def doDownloadX(self, answer):
		if answer:
			selectedimage = self["list"].getCurrent()
			currentSelected = self["list"].l.getCurrentSelection()
			selectedimage = currentSelected[0][0]
			headers, fileurl = self.processAuthLogin(currentSelected[0][1])
			fileloc = self.BackupDirectory + selectedimage
			Tools.CopyFiles.downloadFile(fileurl, fileloc, selectedimage.replace("_usb", ""), headers=headers)
			for job in Components.Task.job_manager.getPendingJobs():
				if job:
					if job.name.startswith(_("Downloading")):
						break
					self.showJobView(job)
			self.close()

	def showJobView(self, job):
		Components.Task.job_manager.in_background = False
		self.session.openWithCallback(self.JobViewCB, JobView, job, cancelable=False, backgroundable=True, afterEventChangeable=False)

	def JobViewCB(self, in_background):
		Components.Task.job_manager.in_background = in_background

	def processAuthLogin(self, url):
		from urllib.parse import urlparse
		headers = None
		parsed = urlparse(url)
		scheme = parsed.scheme
		username = parsed.username if parsed.username else ""
		password = parsed.password if parsed.password else ""
		hostname = parsed.hostname
		port = ":%s" % parsed.port if parsed.port else ""
		query = "?%s" % parsed.query if parsed.query else ""
		if username or password:
			from base64 import b64encode
			base64bytes = b64encode(('%s:%s' % (username, password)).encode())
			headers = {("Authorization").encode(): ("Basic %s" % base64bytes.decode()).encode()}
		return headers, scheme + "://" + hostname + port + parsed.path + query


class ImageManagerSetup(Setup):
	def __init__(self, session):
		Setup.__init__(self, session=session, setup="visionimagemanager", plugin="SystemPlugins/Vision", PluginLanguageDomain=PluginLanguageDomain)
		self["actions"] = ActionMap(["SetupActions", "OkCancelActions", "MenuActions"], {
			"ok": self.keySelect,
			"cancel": self.keyCancel,
			"menu": self.keyMenu,
			"save": self.keySave,
			"left": self.keyLeft,
			"right": self.keyRight
		})

	def keySelect(self):
		Setup.keySelect(self)

	def keyCancel(self):
		Setup.keyCancel(self)

	def keyMenu(self):
		Setup.keyMenu(self)

	def keyLeft(self):
		Setup.keyLeft(self)

	def keyRight(self):
		Setup.keyRight(self)

	def keySave(self):
		config.imagemanager.imagefeed_OV = ConfigText(default="https://images.openvision.dedyn.io/json", fixed_size=False) if config.usage.alternative_imagefeed.value != "all" else ConfigText(default="https://images.openvision.dedyn.io/json%s" % config.usage.alternative_imagefeed.value, fixed_size=False)
		if config.imagemanager.folderprefix.value == "":
			config.imagemanager.folderprefix.value = defaultprefix
		for configElement in (config.imagemanager.imagefeed_OV, config.imagemanager.imagefeed_ATV, config.imagemanager.imagefeed_PLi, config.imagemanager.imagefeed_ViX, config.imagemanager.imagefeed_OBH):
			self.check_URL_format(configElement)
		for x in self["config"].list:
			x[1].save()
		configfile.save()
		self.close()

	def check_URL_format(self, configElement):
		if configElement.value:
			configElement.value = "%s%s" % (not (configElement.value.startswith("http://") or configElement.value.startswith("https://") or configElement.value.startswith("ftp://")) and "http://" or "", configElement.value)
			configElement.value = configElement.value.strip("/")  # remove any trailing slash
		else:
			configElement.value = configElement.default
