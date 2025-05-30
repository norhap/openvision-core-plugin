from .__init__ import _
from enigma import eConsoleAppContainer
from os import listdir, path, stat
from boxbranding import getImageDistro
from Components.About import about
from Components.Console import Console
from Components.Pixmap import Pixmap
from Components.Sources.StaticText import StaticText
from Screens.WizardLanguage import WizardLanguage
from Screens.HelpMenu import ShowRemoteControl
from Screens.MessageBox import MessageBox
from Tools.Directories import fileExists, resolveFilename, SCOPE_PLUGINS
from Tools.Multiboot import bootmviSlot, getSlotImageInfo, getCurrentImage
from Components.SystemInfo import SystemInfo, MODEL
from time import sleep


def setcliJoinZerotier():  # join to ZeroTier
	try:
		with open("/tmp/etc/enigma2/settings", "r") as fr:
			for line in fr.readlines():
				if line.startswith('config.plugins.IPToSAT.networkidzerotier'):
					networkid = line.strip().split('=')[1]
					if networkid:
						eConsoleAppContainer().execute(f'/etc/init.d/zerotier start ; update-rc.d -f zerotier defaults ; sleep 15 ; zerotier-cli join {networkid}')
						break
	except Exception:
		pass


class RestoreWizard(WizardLanguage, ShowRemoteControl):
	def __init__(self, session):
		self.xmlfile = resolveFilename(SCOPE_PLUGINS, "SystemPlugins/Vision/restorewizard.xml")
		WizardLanguage.__init__(self, session, showSteps=False, showStepSlider=False)
		ShowRemoteControl.__init__(self)
		self.setTitle(_("Vision Core Restore Wizard"))
		self.skinName = ["NetworkWizard"]
		self.session = session
		self["wizard"] = Pixmap()
		self["lab1"] = StaticText(_("norhap"))
		self["lab2"] = StaticText(_("Report problems to:"))
		self["lab3"] = StaticText(_("telegram @norhap"))
		self["lab4"] = StaticText(_("Sources are available at:"))
		self["lab5"] = StaticText(_("https://github.com/norhap"))
		self.selectedAction = None
		self.NextStep = None
		self.Text = None
		self.buildListRef = None
		self.didSettingsRestore = False
		self.didPluginRestore = False
		self.PluginsRestore = False
		self.fullbackupfilename = None
		self.delaymess = None
		self.selectedDevice = None
		self.Console = Console()

	def getTranslation(self, text):
		return _(text)

	def listDevices(self):
		devmounts = []
		list = []
		files = []
		mtimes = []
		defaultprefix = getImageDistro()

		for dir in ["/media/%s/backup" % media for media in listdir("/media/") if path.isdir(path.join("/media/", media))]:
			devmounts.append(dir)
		if len(devmounts):
			for devpath in devmounts:
				if path.exists(devpath):
					try:
						files = listdir(devpath)
					except:
						files = []
				else:
					files = []
				if len(files):
					for file in files:
						if MODEL in file:
							if file.endswith(".tar.gz") and "norhap" in file.lower() or file.startswith("%s" % defaultprefix):
								mtimes.append((path.join(devpath, file), stat(path.join(devpath, file)).st_mtime))  # (filname, mtime)
		for file in [x[0] for x in sorted(mtimes, key=lambda x: x[1], reverse=True)]:  # sort by mtime
			list.append((file, file))
		return list

	def settingsdeviceSelectionMade(self, index):
		self.selectedAction = index
		self.settingsdeviceSelect(index)

	def settingsdeviceSelect(self, index):
		self.selectedDevice = index
		self.fullbackupfilename = index
		self.NextStep = 'settingrestorestarted'

	def settingsdeviceSelectionMoved(self):
		self.settingsdeviceSelect(self.selection)

	def pluginsdeviceSelectionMade(self, index):
		self.selectedAction = index
		self.pluginsdeviceSelect(index)

	def pluginsdeviceSelect(self, index):
		self.selectedDevice = index
		self.fullbackupfilename = index
		self.NextStep = 'plugindetection'

	def pluginsdeviceSelectionMoved(self):
		self.pluginsdeviceSelect(self.selection)

	def markDone(self):
		pass

	def listAction(self):
		list = [(_("OK, to perform a restore"), "settingsquestion"), (_("Exit the restore wizard"), "end")]
		return list

	def listAction2(self):
		list = [(_("YES, to restore settings"), "settingsrestore"), (_("NO, do not restore settings"), "pluginsquestion")]
		return list

	def listAction3(self):
		list = []
		if self.didSettingsRestore:
			list.append((_("YES, to restore plugins"), "pluginrestore"))
			list.append((_("NO, do not restore plugins"), "reboot"))
		else:
			list.append((_("YES, to restore plugins"), "pluginsrestoredevice"))
			list.append((_("NO, do not restore plugins"), "end"))
		return list

	def rebootAction(self):
		list = [(_("OK"), "reboot")]
		return list

	def ActionSelectionMade(self, index):
		self.selectedAction = index
		self.ActionSelect(index)

	def ActionSelect(self, index):
		self.NextStep = index

	def ActionSelectionMoved(self):
		self.ActionSelect(self.selection)

	def buildList(self, action):
		if self.NextStep == 'reboot':
			if SystemInfo["hasKexec"]:
				slot = getCurrentImage()
				text = getSlotImageInfo(slot)
				bootmviSlot(text=text, slot=slot)
			if self.didSettingsRestore and path.exists("/tmp/etc/enigma2/settings"):
				self.Console.ePopen("tar -xzvf " + self.fullbackupfilename + " -C /")
			sleep(0.5)
			if path.islink("/etc/resolv.conf"):
				self.Console.ePopen("rm -f /etc/resolv.conf ; mv /run/resolv.conf /etc/")
			self.session.open(MessageBox, _("Finishing restore, your receiver go to restart."), MessageBox.TYPE_INFO, simple=True)
			eConsoleAppContainer().execute("sleep 15 && killall -9 enigma2 && init 6")
		elif self.NextStep == 'settingsquestion' or self.NextStep == 'settingsrestore' or self.NextStep == 'pluginsquestion' or self.NextStep == 'pluginsrestoredevice' or self.NextStep == 'end' or self.NextStep == 'noplugins':
			self.buildListfinishedCB(False)
		elif self.NextStep == 'settingrestorestarted':
			self.Console.ePopen("tar -xzvf " + self.fullbackupfilename + " -C / tmp/ExtraInstalledPlugins tmp/backupkernelversion tmp/backupimageversion", self.settingsRestore_Started)
			self.buildListRef = self.session.openWithCallback(self.buildListfinishedCB, MessageBox, _("Please wait while the system gathers information..."), type=MessageBox.TYPE_INFO, enable_input=False, simple=True)
			self.buildListRef.setTitle(_("Restore wizard"))
		elif self.NextStep == 'plugindetection':
			print('[RestoreWizard] Stage 2: Restoring plugins')
			self.Console.ePopen("tar -xzvf " + self.fullbackupfilename + " -C / tmp/ExtraInstalledPlugins tmp/backupkernelversion tmp/backupimageversion", self.pluginsRestore_Started)
			self.buildListRef = self.session.openWithCallback(self.buildListfinishedCB, MessageBox, _("Please wait while the system gathers information..."), type=MessageBox.TYPE_INFO, enable_input=False, simple=True)
			self.buildListRef.setTitle(_("Restore wizard"))
		elif self.NextStep == 'pluginrestore':
			if self.feeds == 'OK':
				print('[RestoreWizard] Stage 6: Feeds OK, Restoring Plugins')
				print('[RestoreWizard] Console command: ', 'opkg install ' + self.pluginslist + ' ' + self.pluginslist2)
				self.Console.ePopen("opkg update && opkg install " + self.pluginslist + ' ' + self.pluginslist2, self.pluginsRestore_Finished)
				self.buildListRef = self.session.openWithCallback(self.buildListfinishedCB, MessageBox, _("Please wait while plugins restore completes..."), type=MessageBox.TYPE_INFO, enable_input=False, simple=True)
				self.buildListRef.setTitle(_("Restore wizard"))
			elif self.feeds == 'DOWN':
				print('[RestoreWizard] Stage 6: Feeds Down')
				self.didPluginRestore = True
				self.NextStep = 'reboot'
				self.buildListRef = self.session.openWithCallback(self.buildListfinishedCB, MessageBox, _("Sorry the feeds are down for maintenance. Please try using Backup manager to restore plugins later."), type=MessageBox.TYPE_INFO, timeout=30)
				self.buildListRef.setTitle(_("Restore wizard"))
			elif self.feeds == 'BAD':
				print('[RestoreWizard] Stage 6: No Network')
				self.didPluginRestore = True
				self.NextStep = 'reboot'
				self.buildListRef = self.session.openWithCallback(self.buildListfinishedCB, MessageBox, _("Your receiver is not connected to the Internet. Please try using the Backup manager to restore plugins later."), type=MessageBox.TYPE_INFO, timeout=30)
				self.buildListRef.setTitle(_("Restore wizard"))
			elif self.feeds == 'ERROR':
				self.NextStep = 'pluginrestore'
				self.buildListRef = self.session.openWithCallback(self.buildListfinishedCB, MessageBox, _("A background update check is in progress, please try again."), type=MessageBox.TYPE_INFO, timeout=10)
				self.buildListRef.setTitle(_("Restore wizard"))

	def buildListfinishedCB(self, data):
		# self.buildListRef = None
		if data is True:
			self.currStep = self.getStepWithID(self.NextStep)
			self.afterAsyncCode()
		else:
			self.currStep = self.getStepWithID(self.NextStep)
			self.afterAsyncCode()

	def settingsRestore_Started(self, result, retval, extra_args=None):
		self.doRestoreSettings1()

	def doRestoreSettings1(self):
		print('[RestoreWizard] Stage 1: Check Kernel Version')
		if fileExists('/tmp/backupkernelversion'):
			kernelversion = open('/tmp/backupkernelversion').read()
			print('[RestoreWizard] Backup Kernel:', kernelversion)
			print('[RestoreWizard] Current Kernel:', about.getKernelVersionString())
			if kernelversion == about.getKernelVersionString() or about.getKernelVersionString() == "unknown":
				print('[RestoreWizard] Stage 1: kernel OK')
				self.doRestoreSettings2()
			else:
				print('[RestoreWizard] Stage 1: Image ver different')
				self.noVersion = self.session.openWithCallback(self.doNoVersion, MessageBox, _("Sorry, but the file is not compatible with this kernel version."), type=MessageBox.TYPE_INFO, timeout=30)
				self.noVersion.setTitle(_("Restore wizard"))
		else:
			print('[RestoreWizard] Stage 1: No Image ver to check')
			self.noVersion = self.session.openWithCallback(self.doNoVersion, MessageBox, _("Sorry, but the file is not compatible with this kernel version."), type=MessageBox.TYPE_INFO, timeout=30)
			self.noVersion.setTitle(_("Restore wizard"))

	def doNoVersion(self, result=None, retval=None, extra_args=None):
		self.buildListRef.close(True)

	def doRestoreSettings2(self):
		print('[RestoreWizard] Stage 2: Restoring settings')
		self.Console.ePopen("tar -xzvf " + self.fullbackupfilename + " -C /tmp/ etc/enigma2/settings", self.settingRestore_Finished)
		self.pleaseWait = self.session.open(MessageBox, _("Please wait while settings restore completes..."), type=MessageBox.TYPE_INFO, enable_input=False, simple=True)
		self.pleaseWait.setTitle(_("Restore wizard"))

	def settingRestore_Finished(self, result, retval, extra_args=None):
		self.didSettingsRestore = True
		network = [x.split(" ")[3] for x in open("/etc/network/interfaces").read().splitlines() if x.startswith("iface eth0")]
		self.pleaseWait.close()
		self.doRestorePlugins1()

	def pluginsRestore_Started(self, result, retval, extra_args=None):
		self.doRestorePlugins1()

	def pluginsRestore_Finished(self, result, retval, extra_args=None):
		if result:
			print("[RestoreWizard] opkg install result:\n", str(result))
			# if path.exists("/tmp/etc/enigma2/settings") and path.exists("/usr/sbin/zerotier-one"):
				# setcliJoinZerotier()
		self.didPluginRestore = True
		self.NextStep = 'reboot'
		self.buildListRef.close(True)

	def doRestorePlugins1(self):
		print('[RestoreWizard] Stage 3: Check Kernel')
		if fileExists('/tmp/backupkernelversion'):
			kernelversion = open('/tmp/backupkernelversion').read()
			print('[RestoreWizard] Backup Kernel:', kernelversion)
			print('[RestoreWizard] Current Kernel:', about.getKernelVersionString())
			if kernelversion == about.getKernelVersionString():
				print('[RestoreWizard] Stage 3: Kernel and image ver OK')
				self.doRestorePluginsTest()
			else:
				print('[RestoreWizard] Stage 3: Kernel or image version is different')
				if self.didSettingsRestore:
					self.NextStep = 'reboot'
				else:
					self.NextStep = 'noplugins'
				self.buildListRef.close(True)
		else:
			print('[RestoreWizard] Stage 3: No Kernel to check')
			if self.didSettingsRestore:
				self.NextStep = 'reboot'
			else:
				self.NextStep = 'noplugins'
			self.buildListRef.close(True)

	def doRestorePluginsTest(self, result=None, retval=None, extra_args=None):
		if self.delaymess:
			self.delaymess.close()
		print('[RestoreWizard] Stage 4: Feeds Test')
		self.Console.ePopen('ifdown -v -f eth0; ifup -v eth0 && opkg update', self.doRestorePluginsTestComplete)

	def doRestorePluginsTestComplete(self, result=None, retval=None, extra_args=None):
		result2 = result
		print('[RestoreWizard] Stage 4: Feeds test result', result2)
		if result2.find('wget returned 4') != -1:
			self.NextStep = 'reboot'
			self.buildListRef = self.session.openWithCallback(self.buildListfinishedCB, MessageBox, _("Your receiver is not connected to a network. Please try using the Backup manager to restore plugins later when a network connection is available."), type=MessageBox.TYPE_INFO, timeout=30)
			self.buildListRef.setTitle(_("Restore wizard"))
		elif result2.find('wget returned 8') != -1:
			self.NextStep = 'reboot'
			self.buildListRef = self.session.openWithCallback(self.buildListfinishedCB, MessageBox, _("Your receiver could not connect to the plugin feeds at this time. Please try using the Backup manager to restore plugins later."), type=MessageBox.TYPE_INFO, timeout=30)
			self.buildListRef.setTitle(_("Restore wizard"))
		elif result2.find('bad address') != -1:
			self.NextStep = 'reboot'
			self.buildListRef = self.session.openWithCallback(self.buildListfinishedCB, MessageBox, _("Your receiver is not connected to the Internet. Please try using the Backup manager to restore plugins later."), type=MessageBox.TYPE_INFO, timeout=30)
			self.buildListRef.setTitle(_("Restore wizard"))
		elif result2.find('wget returned 1') != -1 or result2.find('wget returned 255') != -1 or result2.find('404 Not Found') != -1:
			self.NextStep = 'reboot'
			self.buildListRef = self.session.openWithCallback(self.buildListfinishedCB, MessageBox, _("Sorry the feeds are down for maintenance. Please try using the Backup manager to restore plugins later."), type=MessageBox.TYPE_INFO, timeout=30)
			self.buildListRef.setTitle(_("Restore wizard"))
		elif result2.find('Collected errors') != -1:
			print('[RestoreWizard] Stage 4: Update is in progress, delaying')
			self.delaymess = self.session.openWithCallback(self.doRestorePluginsTest, MessageBox, _("A background update check is in progress, please try again."), type=MessageBox.TYPE_INFO, timeout=10)
			self.delaymess.setTitle(_("Restore wizard"))
		else:
			print('[RestoreWizard] Stage 4: Feeds OK')
			self.feeds = 'OK'
			self.doListPlugins()

	def doListPlugins(self):
		print('[RestoreWizard] Stage 4: Feeds Test')
		self.Console.ePopen('opkg list-installed', self.doRestorePlugins2)

	def doRestorePlugins2(self, result, retval, extra_args):
		print('[RestoreWizard] Stage 5: Build list of plugins to restore')
		self.pluginslist = ""
		self.pluginslist2 = ""
		plugins = []
		if path.exists('/tmp/ExtraInstalledPlugins'):
			self.pluginslist = []
			for line in result.split("\n"):
				if line:
					parts = line.strip().split()
					plugins.append(parts[0])
			tmppluginslist = open('/tmp/ExtraInstalledPlugins', 'r').readlines()
			for line in tmppluginslist:
				if line:
					parts = line.strip().split()
					if len(parts) > 0 and parts[0] not in plugins:
						self.pluginslist.append(parts[0])

		if path.exists('/tmp/3rdPartyPlugins'):
			self.pluginslist2 = []
			if path.exists('/tmp/3rdPartyPluginsLocation'):
				self.thirdpartyPluginsLocation = open('/tmp/3rdPartyPluginsLocation', 'r').readlines()
				self.thirdpartyPluginsLocation = "".join(self.thirdpartyPluginsLocation)
				self.thirdpartyPluginsLocation = self.thirdpartyPluginsLocation.replace('\n', '')
				self.thirdpartyPluginsLocation = self.thirdpartyPluginsLocation.replace(' ', '%20')
				self.plugfiles = self.thirdpartyPluginsLocation.split('/', 3)
			else:
				self.thirdpartyPluginsLocation = " "

			tmppluginslist2 = open('/tmp/3rdPartyPlugins', 'r').readlines()
			available = None
			for line in tmppluginslist2:
				if line:
					parts = line.strip().split('_')
					if parts[0] not in plugins:
						ipk = parts[0]
						if path.exists(self.thirdpartyPluginsLocation):
							available = listdir(self.thirdpartyPluginsLocation)
						else:
							devmounts = []
							files = []
							self.plugfile = self.plugfiles[3]
							for dir in ["/media/%s/%s" % (media, self.plugfile) for media in listdir("/media/") if path.isdir(path.join("/media/", media))]:
								if "autofs" not in dir or "net" not in dir:
									devmounts.append(dir)
							if len(devmounts):
								for x in devmounts:
									print("[BackupManager] Search dir = %s" % devmounts)
									if path.exists(x):
										self.thirdpartyPluginsLocation = x
										try:
											available = listdir(self.thirdpartyPluginsLocation)
											break
										except:
											continue
						if available:
							for file in available:
								if file:
									fileparts = file.strip().split('_')
									if fileparts[0] == ipk:
										self.thirdpartyPluginsLocation = self.thirdpartyPluginsLocation.replace(' ', '%20')
										ipk = path.join(self.thirdpartyPluginsLocation, file)
										if path.exists(ipk):
											self.pluginslist2.append(ipk)

		if len(self.pluginslist) or len(self.pluginslist2):
			self.doRestorePluginsQuestion()
		else:
			if self.didSettingsRestore:
				self.NextStep = 'reboot'
			else:
				self.NextStep = 'noplugins'
			self.buildListRef.close(True)

	def doRestorePluginsQuestion(self):
		if len(self.pluginslist) or len(self.pluginslist2):
			if len(self.pluginslist):
				self.pluginslist = " ".join(self.pluginslist)
			else:
				self.pluginslist = ""
			if len(self.pluginslist2):
				self.pluginslist2 = " ".join(self.pluginslist2)
			else:
				self.pluginslist2 = ""
			print('[RestoreWizard] Stage 6: Plugins to restore in feeds', self.pluginslist)
			print('[RestoreWizard] Stage 6: Plugins to restore in extra location', self.pluginslist2)
			if self.didSettingsRestore:
				print('[RestoreWizard] Stage 6: proceed to question')
				self.NextStep = 'pluginsquestion'
				self.buildListRef.close(True)
			else:
				print('[RestoreWizard] Stage 6: proceed to restore')
				self.NextStep = 'pluginrestore'
				self.buildListRef.close(True)
		else:
			print('[RestoreWizard] Stage 6: NO Plugins to restore')
			if self.didSettingsRestore:
				self.NextStep = 'reboot'
			else:
				self.NextStep = 'noplugins'
		self.buildListRef.close(True)
