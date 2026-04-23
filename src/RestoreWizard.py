from .__init__ import _
from enigma import eConsoleAppContainer
from subprocess import run
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

fullbackupfilename = None


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
		self.unsatisfiedPlugins = False
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
		global fullbackupfilename
		self.selectedDevice = index
		fullbackupfilename = index
		self.fullbackupfilename = index
		self.NextStep = 'settingrestorestarted'

	def settingsdeviceSelectionMoved(self):
		self.settingsdeviceSelect(self.selection)

	def pluginsdeviceSelectionMade(self, index):
		global fullbackupfilename
		fullbackupfilename = index
		self.selectedAction = index
		self.pluginsdeviceSelect(index)

	def pluginsdeviceSelect(self, index):
		global fullbackupfilename
		fullbackupfilename = index
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
		from Screens.Console import Console
		cmdList = []
		if self.NextStep == 'reboot':
			delay = 8 if not self.unsatisfiedPlugins else 60
			if SystemInfo["hasKexec"]:
				slot = getCurrentImage()
				text = getSlotImageInfo(slot)
				bootmviSlot(text=text, slot=slot)
			if self.didSettingsRestore and path.exists("/tmp/etc/enigma2/settings"):
				cmd = "tar -xzvf " + self.fullbackupfilename + " -C / ; echo '\n  '" + _("Finishing restore your receiver go to restart...") + " ; sleep " + str(delay) + " ; killall -9 enigma2 ; init 6" if not path.islink("/etc/resolv.conf") else "rm -f /etc/resolv.conf ; mv /run/resolv.conf /etc/ ; tar -xzvf " + self.fullbackupfilename + " -C / ; echo '\n  '" + _("Finishing restore your receiver go to restart...") + " ; sleep " + str(delay) + " ; killall -9 enigma2 ; init 6"
				cmdList.append(cmd)
				if cmdList:
					self.session.openWithCallback(self.close, Console, title=self.getTitle(), cmdlist=cmdList, closeOnSuccess=True)
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
				if self.pluginslist and not self.pluginslist2:
					from .BackupManager import RestorePlugins
					self.session.openWithCallback(self.close, RestorePlugins, self.pluginslist)
				if SystemInfo["hasKexec"]:
					slot = getCurrentImage()
					text = getSlotImageInfo(slot)
					bootmviSlot(text=text, slot=slot)
				if self.didSettingsRestore and path.exists("/tmp/etc/enigma2/settings"):
					cmdList.append("tar -xzvf " + self.fullbackupfilename + " -C /")
					if cmdList:
						self.session.openWithCallback(self.close, Console, title=self.getTitle(), cmdlist=cmdList, closeOnSuccess=True)
				elif self.pluginslist2:
					print('[RestoreWizard] Stage 6: Feeds OK, Restoring Plugins')
					print('[RestoreWizard] Console command: ', 'opkg install ' + self.pluginslist2)
					self.Console.ePopen("opkg update && opkg install " + self.pluginslist2, self.pluginsRestore_Finished)
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

	def settingsRestore_Started(self, result, retVal, extra_args=None):
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

	def doNoVersion(self, result=None, retVal=None, extra_args=None):
		self.buildListRef.close(True)

	def doRestoreSettings2(self):
		print('[RestoreWizard] Stage 2: Restoring settings')
		self.Console.ePopen("tar -xzvf " + self.fullbackupfilename + " -C /tmp/ etc/enigma2/settings", self.settingRestore_Finished)
		self.pleaseWait = self.session.open(MessageBox, _("Please wait while settings restore completes..."), type=MessageBox.TYPE_INFO, enable_input=False, simple=True)
		self.pleaseWait.setTitle(_("Restore wizard"))

	def settingRestore_Finished(self, result, retVal, extra_args=None):
		self.didSettingsRestore = True
		network = [x.split(" ")[3] for x in open("/etc/network/interfaces").read().splitlines() if x.startswith("iface eth0")]
		self.pleaseWait.close()
		self.doRestorePlugins1()

	def pluginsRestore_Started(self, result, retVal, extra_args=None):
		self.doRestorePlugins1()

	def pluginsRestore_Finished(self, result, retVal, extra_args=None):
		if result:
			print("[RestoreWizard] opkg install result:\n", str(result))
			"""
			if path.exists("/tmp/etc/enigma2/settings") and path.exists("/usr/sbin/zerotier-one"):
				setcliJoinZerotier()
			"""
		if retVal == 0:
			self.didPluginRestore = True
			self.NextStep = 'reboot'
			self.buildListRef.close(True)
		else:
			self.unsatisfiedPlugins = True
			self.NextStep = 'reboot'
			self.buildListRef.close(True)
			print('[RestoreWizard] Restoring doRestorePlugins2: Couldnt find anything to satisfy')
			self.Console.ePopen('opkg list-installed', self.doRestorePlugins2)

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

	def doRestorePluginsTest(self, result=None, retVal=None, extra_args=None):
		if self.delaymess:
			self.delaymess.close()
		print('[RestoreWizard] Stage 4: Feeds Test')
		self.Console.ePopen('ifdown -v -f eth0; ifup -v eth0 && opkg update', self.doRestorePluginsTestComplete)

	def doRestorePluginsTestComplete(self, result=None, retVal=None, extra_args=None):
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
		self.Console.ePopen('opkg list', self.comparePluginLists)

	def comparePluginLists(self, result, retVal, extra_args):
		self.opkg_available_packages = {p.split()[0] for line in result.split("\n") if (p := line.strip())}  # list of all packages available from the feeds
		self.Console.ePopen("opkg list-installed | egrep 'enigma2-plugin-|task-base|packagegroup-base", self.doRestorePlugins2)

	def doRestorePlugins2(self, result, retVal, extra_args):
		if self.unsatisfiedPlugins is False:
			print('[RestoreWizard] Stage 5: Build list of plugins to restore')
			self.pluginslist = []
			self.pluginslist2 = []
			opkg_installed_packages = {p.split()[0] for line in result.split("\n") if (p := line.strip())}
			if path.exists("/tmp/ExtraInstalledPlugins"):
				with open("/tmp/ExtraInstalledPlugins", "r") as fd:
					self.pluginslist = [p for line in fd.readlines() if (p := line.strip()) and p in self.opkg_available_packages and p not in opkg_installed_packages]
			if path.exists("/tmp/3rdPartyPlugins"):
				thirdpartyPluginsLocation = ""
				tmppluginslist2 = ""
				if path.exists("/tmp/3rdPartyPluginsLocation"):
					with open("/tmp/3rdPartyPluginsLocation", "r") as fd:
						thirdpartyPluginsLocation = fd.readline().strip()
						# print("[RestoreWizard] Restoring Stage 3: thirdpartyPluginsLocation from file", "'%s'" % thirdpartyPluginsLocation)
				thirdpartyPluginsLocation = thirdpartyPluginsLocation.replace(" ", "%20")  # What is this replace for?
				with open("/tmp/3rdPartyPlugins", "r") as fd:
					tmppluginslist2 = [package.split("_")[0] for line in fd.readlines() if (package := line.strip())]  # ".split("_")[0]" should be redundant if the input is correct
				relative_path = len(x := thirdpartyPluginsLocation.split("/", 3)) > 3 and x[3] or None  # expects thirdpartyPluginsLocation to be in the format /media/something/myFolder
				devmounts = relative_path and ["/media/%s/%s" % (media, relative_path) for media in listdir("/media/") if media not in ("autofs", "net") and path.isdir(path.join("/media/", media)) and path.exists("/media/%s/%s" % (media, relative_path))]
				print("[RestoreWizard] search dir = %s" % str(devmounts))
				for ipk in tmppluginslist2:
					available = []
					if ipk and ipk not in opkg_installed_packages:
						if thirdpartyPluginsLocation and path.exists(thirdpartyPluginsLocation):
							available = sorted([y for y in listdir(thirdpartyPluginsLocation) if y.startswith(ipk)], reverse=True)  # sort for most recent by name if multiple versions
						elif devmounts:
							for x in devmounts:
								try:  # Why is this try/except needed? What exception is it protecting against?
									available = sorted([y for y in listdir(x) if y.startswith(ipk)], reverse=True)  # sort for most recent by name if multiple versions
									print("[RestoreWizard] Restoring Stage 3: 3rdPartyPlugin found", x, available)
									thirdpartyPluginsLocation = x
									break
								except Exception as e:
									print("[RestoreWizard] Restoring Stage 3: exception trying to access 3rdPartyPlugin location:", x, "\n", e)
									continue
						if available:
							self.pluginslist2.append(path.join(thirdpartyPluginsLocation, available[0]))
							if ipk in self.pluginslist:
								self.pluginslist.remove(ipk)  # local version takes priority
			if len(self.pluginslist) or len(self.pluginslist2):
				self.doRestorePluginsQuestion()
			else:
				if self.didSettingsRestore:
					self.NextStep = 'reboot'
				else:
					self.NextStep = 'noplugins'
				self.buildListRef.close(True)
		else:
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
							self.pluginslist = parts[0]
							run(["opkg install " + self.pluginslist], shell=True).stdout  # Forces the installation of packages available in the feeds.
			print('[RestoreWizard] Restoring Stage 4: Complete with unsatisfactory packages not included')

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
