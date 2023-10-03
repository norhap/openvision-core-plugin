import re
from os import path, makedirs, remove, rename, symlink, mkdir, listdir, unlink, system
from datetime import datetime
from time import time
from enigma import eTimer, eConsoleAppContainer

from .__init__ import _
import Components.Task
from Components.ActionMap import ActionMap
from Components.Sources.StaticText import StaticText
from Components.Label import Label
from Components.Button import Button
from Components.ScrollLabel import ScrollLabel
from Components.Pixmap import MultiPixmap
from Components.config import configfile, config, ConfigSubsection, ConfigYesNo, ConfigNumber, ConfigLocations, getConfigListEntry, ConfigSelection
from Components.Console import Console
from Components.FileList import MultiFileSelectList
from Components.PluginComponent import plugins
from Tools.camcontrol import CamControl
from Tools.Directories import resolveFilename, SCOPE_PLUGINS
from Screens.Screen import Screen
from Screens.MessageBox import MessageBox
from Components.ConfigList import ConfigListScreen
from process import ProcessList

config.softcammanager = ConfigSubsection()
config.softcammanager.softcams_autostart = ConfigLocations(default='')
config.softcammanager.softcamtimerenabled = ConfigYesNo(default=True)
config.softcammanager.softcamtimer = ConfigNumber(default=6)
config.softcammanager.showinextensions = ConfigYesNo(default=True)
config.misc.softcams = ConfigSelection(default="None", choices=CamControl("softcam").getList())

softcamautopoller = None

wicardd = str(ProcessList().named("wicardd")).strip("[]")
cccam = str(ProcessList().named("CCcam")).strip("[]")
if config.softcammanager.softcams_autostart.value not in ("wicardd", "CCcam") and config.misc.softcams.value not in ("wicardd", "CCcam"):
	if wicardd:
		Console().ePopen('kill -9 %s' % wicardd)
	if cccam:
		Console().ePopen('kill -9 %s' % cccam)


def updateExtensions(configElement):
	plugins.clearPluginList()
	plugins.readPluginList(resolveFilename(SCOPE_PLUGINS))


config.softcammanager.showinextensions.addNotifier(updateExtensions, initial_call=False)


def SoftcamAutostart(reason, session=None, **kwargs):
	"""called with reason=1 to during shutdown, with reason=0 at startup?"""
	global softcamautopoller
	if reason == 0:
		link = "/etc/init.d/softcam"
		print("[SoftcamAutostart] config.misc.softcams.value=%s" % (config.misc.softcams.value))
		if path.exists(link) and config.misc.softcams.value != "None":
			scr = "softcam.%s" % config.misc.softcams.value
			unlink(link)
			symlink(scr, link)
			cmd = "%s %s" % (link, "start")
			print("[SoftcamAutostart][command]Executing %s" % cmd)
			eConsoleAppContainer().execute(cmd)
			softcamautopoller = SoftcamAutoPoller()
			softcamautopoller.start()
		else:
			print("[SoftcamManager] AutoStart Enabled")
			if path.exists("/tmp/SoftcamsDisableCheck"):
				remove("/tmp/SoftcamsDisableCheck")
			softcamautopoller = SoftcamAutoPoller()
			softcamautopoller.start()
	elif reason == 1:
		# Stop Poller
		if softcamautopoller is not None:
			softcamautopoller.stop()
			softcamautopoller = None


class VISIONSoftcamManager(Screen):
	skin = """
	<screen name="VISIONSoftcamManager" position="center,center" size="560,400">
		<ePixmap pixmap="buttons/red.png" position="0,0" size="140,40" alphaTest="blend"/>
		<ePixmap pixmap="buttons/green.png" position="140,0" size="140,40" alphaTest="blend"/>
		<ePixmap pixmap="buttons/yellow.png" position="280,0" size="140,40" alphaTest="blend"/>
		<ePixmap pixmap="buttons/blue.png" position="420,0" size="140,40" alphaTest="blend"/>
		<widget name="key_red" position="0,0" zPosition="1" size="140,40" font="Regular;20" horizontalAlignment="center" verticalAlignment="center" backgroundColor="#9f1313" transparent="1"/>
		<widget name="key_green" position="140,0" zPosition="1" size="140,40" font="Regular;20" horizontalAlignment="center" verticalAlignment="center" backgroundColor="#1f771f" transparent="1"/>
		<widget name="key_yellow" position="280,0" zPosition="1" size="140,40" font="Regular;20" horizontalAlignment="center" verticalAlignment="center" backgroundColor="#a08500" transparent="1"/>
		<widget name="key_blue" position="420,0" zPosition="1" size="140,40" font="Regular;20" horizontalAlignment="center" verticalAlignment="center" backgroundColor="#a08500" transparent="1"/>
		<widget name="lab6" position="40,60" size="170,20" font="Regular; 22" horizontalAlignment="right" zPosition="2" transparent="0"/>
		<widget name="list" position="225,60" size="240,100" transparent="0" scrollbarMode="showOnDemand"/>
		<widget name="lab7" position="40,165" size="170,30" font="Regular; 22" horizontalAlignment="right" zPosition="2" transparent="0"/>
		<widget name="activecam" position="225,166" size="240,100" font="Regular; 20" horizontalAlignment="left" zPosition="2" transparent="0" noWrap="1"/>
		<applet type="onLayoutFinish">
			self["list"].instance.setItemHeight(25)
		</applet>
	</screen>"""

	def __init__(self, session):
		Screen.__init__(self, session)
		self.setTitle(_("Vision Softcam"))
		self["lab1"] = StaticText(_("norhap"))
		self["lab2"] = StaticText(_("Report problems to:"))
		self["lab3"] = StaticText(_("telegram @norhap"))
		self["lab4"] = StaticText(_("Sources are available at:"))
		self["lab5"] = StaticText(_("https://github.com/norhap"))

		self['lab6'] = Label(_('Select:'))
		self['lab7'] = Label(_('Active:'))
		self['activecam'] = Label()
		self.onChangedEntry = []

		self.sentsingle = ""
		self.selectedFiles = config.softcammanager.softcams_autostart.value
		self.defaultDir = '/usr/softcams/'
		self.emlist = MultiFileSelectList(self.selectedFiles, self.defaultDir, showDirectories=False)
		self["list"] = self.emlist

		self['myactions'] = ActionMap(['ColorActions', 'OkCancelActions', "TimerEditActions", "MenuActions"], {
			'ok': self.keyStart,
			'cancel': self.close,
			'red': self.close,
			'green': self.keyStart,
			'yellow': self.getRestartPID,
			'blue': self.changeSelectionState,
			'log': self.showLog,
			'menu': self.createSetup,
		}, -1)

		self["key_red"] = Button(_("Close"))
		self["key_green"] = StaticText("")
		self["key_yellow"] = StaticText("")
		self["key_blue"] = StaticText("")

		self["key_menu"] = StaticText(_("MENU"))
		self["key_info"] = StaticText(_("INFO"))

		self.currentactivecam = ""
		self.activityTimer = eTimer()
		self.activityTimer.timeout.get().append(self.getActivecam)
		self.Console = Console()
		self.showActivecam()
		if self.selectionChanged not in self["list"].onSelectionChanged:
			self["list"].onSelectionChanged.append(self.selectionChanged)

	def createSummary(self):
		from Screens.PluginBrowser import PluginBrowserSummary
		return PluginBrowserSummary

	def selectionChanged(self):
		cams = []
		cams = listdir('/usr/softcams')
		selcam = ''
		if cams:
			current = self["list"].getCurrent()[0]
			selcam = current[0]
			print('[SoftcamManager] Selected cam: ' + str(selcam))
			if self.currentactivecam.find(selcam) < 0:
				self["key_green"].setText(_("Start"))
				self["key_yellow"].setText("")
			else:
				self["key_green"].setText(_("Stop"))
				self["key_yellow"].setText(_("Restart"))

			if current[2] is True:
				self["key_blue"].setText(_("Disable startup"))
			else:
				self["key_blue"].setText(_("Enable startup"))
			self.saveSelection()
		desc = _('Active:') + ' ' + self['activecam'].text
		for cb in self.onChangedEntry:
			cb(selcam, desc)

	def changeSelectionState(self):
		cams = []
		if path.exists('/usr/softcams/'):
			cams = listdir('/usr/softcams')
		if cams:
			self["list"].changeSelectionState()
			self.selectedFiles = self["list"].getSelectedList()

	def saveSelection(self):
		self.selectedFiles = self["list"].getSelectedList()
		config.softcammanager.softcams_autostart.value = self.selectedFiles
		config.softcammanager.softcams_autostart.save()
		configfile.save()

	def showActivecam(self):
		scanning = _("Wait please while scanning\nfor softcam's...")
		self['activecam'].setText(scanning)
		self.activityTimer.start(10)

	def getActivecam(self):
		self.activityTimer.stop()
		active = []
		for x in self["list"].list:
			active.append(x[0][0])
		activelist = ",".join(active)
		if activelist:
			self.Console.ePopen("ps.procps -C " + activelist + " | grep -v 'CMD' | sed 's/</ /g' | awk '{print $4}' | awk '{a[$1] = $0} END { for (x in a) { print a[x] } }'", self.showActivecam2)
		else:
			self['activecam'].setText('')
			self['activecam'].show()
		# self.Console.ePopen("ps.procps | grep softcams | grep -v 'grep' | sed 's/</ /g' | awk '{print $5}' | awk '{a[$1] = $0} END { for (x in a) { print a[x] } }' | awk -F'[/]' '{print $4}'", self.showActivecam2)

	def showActivecam2(self, result, retval, extra_args):
		if retval == 0:
			self.currentactivecamtemp = str(result)
			self.currentactivecam = "".join([s for s in self.currentactivecamtemp.splitlines(True) if s.strip("\r\n")])
			self.currentactivecam = self.currentactivecam.replace("\n", ", ")
			if path.exists("/tmp/SoftcamsScriptsRunning"):
				file = open("/tmp/SoftcamsScriptsRunning")
				SoftcamsScriptsRunning = file.read()
				file.close()
				SoftcamsScriptsRunning = SoftcamsScriptsRunning.replace("\n", ", ")
				self.currentactivecam += SoftcamsScriptsRunning
			print("[SoftcamManager] Active:%s SoftcamSetup:%s" % (self.currentactivecam, config.misc.softcams.value))
			if config.misc.softcams.value != "None":
				self["activecam"].setText(_("From Softcam Setup [%s].\n%s") % (config.misc.softcams.value, self.currentactivecam))
			else:
				self["activecam"].setText(self.currentactivecam)
			self["activecam"].show()
		else:
			print("[SoftcamManager] Result failed: " + str(result))
		self.selectionChanged()

	def keyStart(self):
		cams = []
		if path.exists('/usr/softcams/'):
			cams = listdir('/usr/softcams')
		if cams:
			self.sel = self['list'].getCurrent()[0]
			selcam = self.sel[0]
			if self.currentactivecam.find(selcam) < 0:
				if selcam.lower().endswith('oscam'):
					if not path.exists('/etc/tuxbox/config/oscam/oscam.conf'):
						self.session.open(MessageBox, _("No config files found, please setup OSCam first\nin /etc/tuxbox/config/oscam."), MessageBox.TYPE_INFO, timeout=10, close_on_any_key=True)
					else:
						self.session.openWithCallback(self.showActivecam, VISIONStartCam, self.sel[0])
				elif selcam.lower().endswith('smod'):
					if not path.exists('/etc/tuxbox/config/oscam-smod/oscam.conf'):
						self.session.open(MessageBox, _("No config files found, please setup OSCam-smod first\nin /etc/tuxbox/config/oscam-smod."), MessageBox.TYPE_INFO, timeout=10, close_on_any_key=True)
					else:
						self.session.openWithCallback(self.showActivecam, VISIONStartCam, self.sel[0])
				elif selcam.lower().endswith('emu'):
					if not path.exists('/etc/tuxbox/config/oscam-emu/oscam.conf'):
						self.session.open(MessageBox, _("No config files found, please setup OSCam-emu first\nin /etc/tuxbox/config/oscam-emu."), MessageBox.TYPE_INFO, timeout=10, close_on_any_key=True)
					else:
						self.session.openWithCallback(self.showActivecam, VISIONStartCam, self.sel[0])
				elif selcam.lower().startswith('ncam'):
					if not path.exists('/etc/tuxbox/config/ncam/ncam.conf'):
						self.session.open(MessageBox, _("No config files found, please setup NCam first\nin /etc/tuxbox/config/ncam."), MessageBox.TYPE_INFO, timeout=10, close_on_any_key=True)
					else:
						self.session.openWithCallback(self.showActivecam, VISIONStartCam, self.sel[0])
				elif selcam.lower().startswith('wicardd'):
					if not path.exists('/etc/tuxbox/config/wicardd/wicardd.conf'):
						self.session.open(MessageBox, _("No config files found, please setup Wicardd first\nin /etc/tuxbox/config/wicardd."), MessageBox.TYPE_INFO, timeout=10, close_on_any_key=True)
					else:
						self.session.openWithCallback(self.showActivecam, VISIONStartCam, self.sel[0])
				elif selcam.startswith('CCcam') or selcam.startswith('mgcamd'):
					if not path.exists('/etc/CCcam.cfg') and selcam.startswith('CCcam'):
						self.session.open(MessageBox, _("No config files found, please setup CCcam first\nin /etc/CCcam.cfg."), MessageBox.TYPE_INFO, timeout=10, close_on_any_key=True)
					if not path.exists('/usr/keys/mg_cfg') and selcam.startswith('mgcamd'):
						self.session.open(MessageBox, _("No config files found, please setup MGcamd first\nin /usr/keys."), MessageBox.TYPE_INFO, timeout=10, close_on_any_key=True)
					else:
						self.session.openWithCallback(self.showActivecam, VISIONStartCam, self.sel[0]), self.Console.ePopen('sh /etc/init.d/softcam.%s start' % selcam)
			else:
				self.session.openWithCallback(self.showActivecam, VISIONStopCam, self.sel[0])
			# if selcam.startswith('mgcamd'): # code no increse RAM for MGcamd.
				# mgcamd = str(ProcessList().named("mgcamd")).strip("[]")
				# if not mgcamd:
				# self.session.openWithCallback(self.showActivecam, VISIONStartCam, self.sel[0]), self.Console.ePopen('sh /etc/init.d/softcam.%s start' % selcam)

	def getRestartPID(self):
		cams = []
		if path.exists('/usr/softcams/'):
			cams = listdir('/usr/softcams')
		if cams:
			self.sel = self['list'].getCurrent()[0]
			selectedcam = self.sel[0]
			self.Console.ePopen("pidof " + selectedcam, self.keyRestart, selectedcam)

	def keyRestart(self, result, retval, extra_args):
		selectedcam = extra_args
		strpos = self.currentactivecam.find(selectedcam)
		if strpos < 0:
			return
		else:
			if retval == 0:
				stopcam = str(result)
				print('[SoftcamManager] Stopping ' + selectedcam + ' PID ' + stopcam.replace("\n", ""))
				now = datetime.now()
				open('/tmp/cam.check.log', 'a').write(now.strftime("%Y-%m-%d %H:%M") + ": Stopping: " + selectedcam + "\n")
				self.Console.ePopen("kill -9 " + stopcam.replace("\n", ""))
			else:
				print('[SoftcamManager] RESULT FAILED: ' + str(result))
			if selectedcam.lower().endswith('oscam') and path.exists('/etc/tuxbox/config/oscam/oscam.conf'):
				self.session.openWithCallback(self.showActivecam, VISIONStartCam, self.sel[0])
			elif selectedcam.lower().startswith('ncam') and path.exists('/etc/tuxbox/config/ncam/ncam.conf'):
				self.session.openWithCallback(self.showActivecam, VISIONStartCam, self.sel[0])
			elif selectedcam.lower().endswith('smod') and path.exists('/etc/tuxbox/config/oscam-smod/oscam.conf'):
				self.session.openWithCallback(self.showActivecam, VISIONStartCam, self.sel[0])
			elif selectedcam.lower().endswith('emu') and path.exists('/etc/tuxbox/config/oscam-emu/oscam.conf'):
				self.session.openWithCallback(self.showActivecam, VISIONStartCam, self.sel[0])
			elif selectedcam.lower().startswith('wicardd') and path.exists('/etc/tuxbox/config/wicardd/wicardd.conf'):
				self.session.openWithCallback(self.showActivecam, VISIONStartCam, self.sel[0])
			elif selectedcam.startswith('mgcamd') and path.exists('/usr/keys/mg_cfg'):
				self.session.openWithCallback(self.showActivecam, VISIONStartCam, self.sel[0])
			elif selectedcam.startswith('CCcam') and path.exists('/etc/CCcam.cfg'):
				self.session.openWithCallback(self.showActivecam, VISIONStartCam, self.sel[0])
			elif selectedcam.lower().startswith('oscam') and not path.exists('/etc/tuxbox/config/oscam/oscam.conf'):
				if not path.exists('/etc/tuxbox/config/oscam'):
					makedirs('/etc/tuxbox/config/oscam')
				self.session.open(MessageBox, _("No config files found, please setup OSCam first\nin /etc/tuxbox/config/oscam."), MessageBox.TYPE_INFO, timeout=10, close_on_any_key=True)
			elif selectedcam.lower().endswith('ncam') and not path.exists('/etc/tuxbox/config/ncam/ncam.conf'):
				if not path.exists('/etc/tuxbox/config/ncam'):
					makedirs('/etc/tuxbox/config/ncam')
				self.session.open(MessageBox, _("No config files found, please setup NCam first\nin /etc/tuxbox/config/ncam."), MessageBox.TYPE_INFO, timeout=10, close_on_any_key=True)
			elif selectedcam.lower().endswith('emu') and not path.exists('/etc/tuxbox/config/oscam-emu/oscam.conf'):
				if not path.exists('/etc/tuxbox/config/oscam-emu'):
					makedirs('/etc/tuxbox/config/oscam-emu')
				self.session.open(MessageBox, _("No config files found, please setup OSCam-emu first\nin /etc/tuxbox/config/oscam-emu."), MessageBox.TYPE_INFO, timeout=10, close_on_any_key=True)
			elif selectedcam.lower().endswith('oscam-smod') and not path.exists('/etc/tuxbox/config/oscam-smod/oscam.conf'):
				if not path.exists('/etc/tuxbox/config/oscam-smod'):
					makedirs('/etc/tuxbox/config/oscam-smod')
				self.session.open(MessageBox, _("No config files found, please setup OSCam-smod first\nin /etc/tuxbox/config/oscam-smod."), MessageBox.TYPE_INFO, timeout=10, close_on_any_key=True)
			elif selectedcam.lower().startswith('wicardd') and not path.exists('/etc/tuxbox/config/wicardd/wicardd.conf'):
				if not path.exists('/etc/tuxbox/config/wicardd'):
					makedirs('/etc/tuxbox/config/wicardd')
				self.session.open(MessageBox, _("No config files found, please setup Wicardd first\nin /etc/tuxbox/config/wicardd."), MessageBox.TYPE_INFO, timeout=10, close_on_any_key=True)
			elif selectedcam.lower().startswith('mgcamd') and not path.exists('/usr/keys/mg_cfg'):
				if not path.exists('/usr/keys'):
					makedirs('/usr/keys')
				self.session.open(MessageBox, _("No config files found, please setup MgCamd first\nin /usr/keys."), MessageBox.TYPE_INFO, timeout=10, close_on_any_key=True)

	def showLog(self):
		self.session.open(VISIONSoftcamLog)

	def createSetup(self):
		self.session.open(VISIONSoftcamMenu)

	def myclose(self):
		self.close()


class VISIONSoftcamMenu(ConfigListScreen, Screen):
	skin = """
		<screen name="VISIONSoftcamMenu" position="center,center" size="500,285" title="Softcam Menu">
			<ePixmap pixmap="buttons/red.png" position="0,0" size="140,40" alphaTest="blend" />
			<ePixmap pixmap="buttons/green.png" position="140,0" size="140,40" alphaTest="blend" />
			<widget name="key_red" position="0,0" zPosition="1" size="140,40" font="Regular;20" horizontalAlignment="center" verticalAlignment="center" backgroundColor="#9f1313" transparent="1" />
			<widget name="key_green" position="140,0" zPosition="1" size="140,40" font="Regular;20" horizontalAlignment="center" verticalAlignment="center" backgroundColor="#1f771f" transparent="1" />
			<widget name="config" position="10,45" size="480,250" scrollbarMode="showOnDemand" />
		</screen>"""

	def __init__(self, session):
		Screen.__init__(self, session)
		self.skinName = "VISIONSoftcamMenu"
		Screen.setTitle(self, _("Vision Softcam setup"))
		self["lab1"] = StaticText(_("norhap"))
		self["lab2"] = StaticText(_("Report problems to:"))
		self["lab3"] = StaticText(_("telegram @norhap"))
		self["lab4"] = StaticText(_("Sources are available at:"))
		self["lab5"] = StaticText(_("https://github.com/norhap"))

		self.onChangedEntry = []
		self.list = []
		ConfigListScreen.__init__(self, self.list, session=self.session, on_change=self.changedEntry)
		self.createSetup()

		self["actions"] = ActionMap(["SetupActions", "MenuActions"], {
			"cancel": self.keyCancel,
			"save": self.keySave,
			"menu": self.closeRecursive,
		}, -2)
		self["key_red"] = Button(_("Cancel"))
		self["key_green"] = Button(_("Save"))

	def createSetup(self):
		self.editListEntry = None
		self.list = []
		self.list.append(getConfigListEntry(_("Enable frozen check"), config.softcammanager.softcamtimerenabled))
		if config.softcammanager.softcamtimerenabled.value:
			self.list.append(getConfigListEntry(_("Check interval on minutes"), config.softcammanager.softcamtimer))
		self["config"].list = self.list
		self["config"].setList(self.list)

	def keyLeft(self):
		ConfigListScreen.keyLeft(self)
		self.createSetup()

	def keyRight(self):
		ConfigListScreen.keyRight(self)
		self.createSetup()

	def changedEntry(self):
		for x in self.onChangedEntry:
			x()

	def getCurrentEntry(self):
		return self["config"].getCurrent()[0]

	def getCurrentValue(self):
		return str(self["config"].getCurrent()[1].getText())

	def keySave(self):
		for x in self["config"].list:
			x[1].save()
		if config.softcammanager.softcamtimerenabled.value:
			print("[SoftcamManager] Timer Check Enabled")
			softcamautopoller.start()
		else:
			print("[SoftcamManager] Timer Check Disabled")
			softcamautopoller.stop()
		self.close()

	def keyCancel(self):
		for x in self["config"].list:
			x[1].cancel()
		self.close()


class VISIONStartCam(Screen):
	skin = """
	<screen name="VISIONStartCam" position="center,center" size="484, 150" title="Starting Softcam">
		<widget name="connect" position="217, 0" size="64,64" zPosition="2" pixmaps="Vision_HD_Common/busy/busy1.png,Vision_HD_Common/busy/busy2.png,Vision_HD_Common/busy/busy3.png,Vision_HD_Common/busy/busy4.png,Vision_HD_Common/busy/busy5.png,Vision_HD_Common/busy/busy6.png,Vision_HD_Common/busy/busy7.png,Vision_HD_Common/busy/busy8.png,Vision_HD_Common/busy/busy9.png,Vision_HD_Common/busy/busy9.png,Vision_HD_Common/busy/busy10.png,Vision_HD_Common/busy/busy11.png,Vision_HD_Common/busy/busy12.png,Vision_HD_Common/busy/busy13.png,Vision_HD_Common/busy/busy14.png,Vision_HD_Common/busy/busy15.png,Vision_HD_Common/busy/busy17.png,Vision_HD_Common/busy/busy18.png,Vision_HD_Common/busy/busy19.png,Vision_HD_Common/busy/busy20.png,Vision_HD_Common/busy/busy21.png,Vision_HD_Common/busy/busy22.png,Vision_HD_Common/busy/busy23.png,Vision_HD_Common/busy/busy24.png"  transparent="1" alphaTest="blend"/>
		<widget name="lab6" position="10, 80" horizontalAlignment="center" size="460,60" zPosition="1" font="Regular;20" verticalAlignment="top" transparent="1"/>
	</screen>"""

	def __init__(self, session, selectedcam):
		Screen.__init__(self, session)
		Screen.setTitle(self, _("Softcam starting..."))
		self["lab1"] = StaticText(_("norhap"))
		self["lab2"] = StaticText(_("Report problems to:"))
		self["lab3"] = StaticText(_("telegram @norhap"))
		self["lab4"] = StaticText(_("Sources are available at:"))
		self["lab5"] = StaticText(_("https://github.com/norhap"))
		self['connect'] = MultiPixmap()
		self['lab6'] = Label(_("Please wait while starting\n") + selectedcam + '...')
		global startselectedcam
		startselectedcam = selectedcam
		self.Console = Console()
		self.activityTimer = eTimer()
		self.activityTimer.timeout.get().append(self.updatepix)
		self.onShow.append(self.startShow)
		self.onClose.append(self.delTimer)

	def startShow(self):
		self.count = 0
		self['connect'].setPixmapNum(0)
		if startselectedcam.endswith('.sh'):
			if path.exists('/tmp/SoftcamsScriptsRunning'):
				file = open('/tmp/SoftcamsScriptsRunning')
				data = file.read()
				file.close()
				if data.find(startselectedcam) >= 0:
					filewrite = open('/tmp/SoftcamsScriptsRunning.tmp', 'w')
					fileread = open('/tmp/SoftcamsScriptsRunning')
					filewrite.writelines([l for l in fileread.readlines() if startselectedcam not in l])
					fileread.close()
					filewrite.close()
					rename('/tmp/SoftcamsScriptsRunning.tmp', '/tmp/SoftcamsScriptsRunning')
				elif data.find(startselectedcam) < 0:
					fileout = open('/tmp/SoftcamsScriptsRunning', 'a')
					line = startselectedcam + '\n'
					fileout.write(line)
					fileout.close()
			else:
				fileout = open('/tmp/SoftcamsScriptsRunning', 'w')
				line = startselectedcam + '\n'
				fileout.write(line)
				fileout.close()
			print('[SoftcamManager] Starting ' + startselectedcam)
			output = open('/tmp/cam.check.log', 'a')
			now = datetime.now()
			output.write(now.strftime("%Y-%m-%d %H:%M") + ": Starting " + startselectedcam + "\n")
			output.close()
			self.Console.ePopen('/usr/softcams/' + startselectedcam + ' start')
		else:
			if path.exists('/tmp/SoftcamsDisableCheck'):
				file = open('/tmp/SoftcamsDisableCheck')
				data = file.read()
				file.close()
				if data.find(startselectedcam) >= 0:
					output = open('/tmp/cam.check.log', 'a')
					now = datetime.now()
					output.write(now.strftime("%Y-%m-%d %H:%M") + ": Initialised timed check for " + stopselectedcam + "\n")
					output.close()
					fileread = open('/tmp/SoftcamsDisableCheck')
					filewrite = open('/tmp/SoftcamsDisableCheck.tmp', 'w')
					filewrite.writelines([l for l in fileread.readlines() if startselectedcam not in l])
					fileread.close()
					filewrite.close()
					rename('/tmp/SoftcamsDisableCheck.tmp', '/tmp/SoftcamsDisableCheck')
			print('[SoftcamManager] Starting ' + startselectedcam)
			output = open('/tmp/cam.check.log', 'a')
			now = datetime.now()
			output.write(now.strftime("%Y-%m-%d %H:%M") + ": Starting " + startselectedcam + "\n")
			output.close()
			self.Console.ePopen('sh /etc/init.d/softcam.%s start' % startselectedcam)

		self.activityTimer.start(1)

	def updatepix(self):
		self.activityTimer.stop()
		maxcount = 25
		if self.count < maxcount:  # timer on screen
			self["connect"].setPixmapNum(self.count % 24)
			self.activityTimer.start(120)  # cycle speed
			self.count += 1
		else:
			self.hide()
			self.close()

	def delTimer(self):
		del self.activityTimer


class VISIONStopCam(Screen):
	skin = """
	<screen name="VISIONStopCam" position="center,center" size="484, 150">
		<widget name="connect" position="217, 0" size="64,64" zPosition="2" pixmaps="Vision_HD_Common/busy/busy1.png,Vision_HD_Common/busy/busy2.png,Vision_HD_Common/busy/busy3.png,Vision_HD_Common/busy/busy4.png,Vision_HD_Common/busy/busy5.png,Vision_HD_Common/busy/busy6.png,Vision_HD_Common/busy/busy7.png,Vision_HD_Common/busy/busy8.png,Vision_HD_Common/busy/busy9.png,Vision_HD_Common/busy/busy9.png,Vision_HD_Common/busy/busy10.png,Vision_HD_Common/busy/busy11.png,Vision_HD_Common/busy/busy12.png,Vision_HD_Common/busy/busy13.png,Vision_HD_Common/busy/busy14.png,Vision_HD_Common/busy/busy15.png,Vision_HD_Common/busy/busy17.png,Vision_HD_Common/busy/busy18.png,Vision_HD_Common/busy/busy19.png,Vision_HD_Common/busy/busy20.png,Vision_HD_Common/busy/busy21.png,Vision_HD_Common/busy/busy22.png,Vision_HD_Common/busy/busy23.png,Vision_HD_Common/busy/busy24.png"  transparent="1" alphaTest="blend"/>
		<widget name="lab6" position="10, 80" horizontalAlignment="center" size="460,60" zPosition="1" font="Regular;20" verticalAlignment="top" transparent="1"/>
	</screen>"""

	def __init__(self, session, selectedcam):
		Screen.__init__(self, session)
		global stopselectedcam
		stopselectedcam = selectedcam
		Screen.setTitle(self, _("Softcam stopping..."))
		self["lab1"] = StaticText(_("norhap"))
		self["lab2"] = StaticText(_("Report problems to:"))
		self["lab3"] = StaticText(_("telegram @norhap"))
		self["lab4"] = StaticText(_("Sources are available at:"))
		self["lab5"] = StaticText(_("https://github.com/norhap"))
		self['connect'] = MultiPixmap()
		self['lab6'] = Label(_("Please wait while stopping\n") + selectedcam + '...')
		self.Console = Console()
		self.activityTimer = eTimer()
		self.activityTimer.timeout.get().append(self.updatepix)
		self.onShow.append(self.getStopPID)
		self.onClose.append(self.delTimer)

	def getStopPID(self):
		if stopselectedcam.endswith('.sh'):
			self.curpix = 0
			self.count = 0
			self['connect'].setPixmapNum(0)
			print('[SoftcamManager] Stopping ' + stopselectedcam)
			output = open('/tmp/cam.check.log', 'a')
			now = datetime.now()
			output.write(now.strftime("%Y-%m-%d %H:%M") + ": Stopping " + stopselectedcam + "\n")
			output.close()
			self.Console.ePopen('/usr/softcams/' + stopselectedcam + ' stop')
			if path.exists('/tmp/SoftcamsScriptsRunning'):
				remove('/tmp/SoftcamsScriptsRunning')
			if path.exists('/etc/SoftcamsAutostart'):
				file = open('/etc/SoftcamsAutostart')
				data = file.read()
				file.close()
				finddata = data.find(stopselectedcam)
				if data.find(stopselectedcam) >= 0:
					print('[SoftcamManager] Temporarily disabled timed check for ' + stopselectedcam)
					output = open('/tmp/cam.check.log', 'a')
					now = datetime.now()
					output.write(now.strftime("%Y-%m-%d %H:%M") + ": Temporarily disabled timed check for " + stopselectedcam + "\n")
					output.close()
					fileout = open('/tmp/SoftcamsDisableCheck', 'a')
					line = stopselectedcam + '\n'
					fileout.write(line)
					fileout.close()
			self.activityTimer.start(1)
		else:
			self.Console.ePopen("pidof " + stopselectedcam, self.startShow)

	def startShow(self, result, retval, extra_args):
		if retval == 0:
			self.count = 0
			self['connect'].setPixmapNum(0)
			stopcam = str(result)
			print("[SoftcamManager][startShow] stopcam=%s" % stopcam)
			if path.exists('/etc/SoftcamsAutostart'):
				data = open('/etc/SoftcamsAutostart').read()
				finddata = data.find(stopselectedcam)
				if data.find(stopselectedcam) >= 0:
					print('[SoftcamManager] Temporarily disabled timed check for ' + stopselectedcam)
					output = open('/tmp/cam.check.log', 'a')
					now = datetime.now()
					output.write(now.strftime("%Y-%m-%d %H:%M") + ": Temporarily disabled timed check for " + stopselectedcam + "\n")
					output.close()
					fileout = open('/tmp/SoftcamsDisableCheck', 'a')
					line = stopselectedcam + '\n'
					fileout.write(line)
					fileout.close()
			print('[SoftcamManager] Stopping ' + stopselectedcam + ' PID ' + stopcam.replace("\n", ""))
			output = open('/tmp/cam.check.log', 'a')
			now = datetime.now()
			output.write(now.strftime("%Y-%m-%d %H:%M") + ": Stopping " + stopselectedcam + "\n")
			output.close()
			self.Console.ePopen("kill -9 " + stopcam.replace("\n", ""))
			self.activityTimer.start(1)

	def updatepix(self):
		self.activityTimer.stop()
		if self.count < 25:  # timer on screen
			self["connect"].setPixmapNum(self.count % 24)
			self.activityTimer.start(120)  # cycle speed
			self.count += 1
		else:
			self.hide()
			self.close()

	def delTimer(self):
		del self.activityTimer


class VISIONSoftcamLog(Screen):
	skin = """
<screen name="VISIONSoftcamLog" position="center,center" size="560,400">
	<widget name="list" position="0,0" size="560,400" font="Regular;14"/>
</screen>"""

	def __init__(self, session):
		self.session = session
		Screen.__init__(self, session)
		self.setTitle(_("Vision Softcam logs"))
		self["lab1"] = StaticText(_("norhap"))
		self["lab2"] = StaticText(_("Report problems to:"))
		self["lab3"] = StaticText(_("telegram @norhap"))
		self["lab4"] = StaticText(_("Sources are available at:"))
		self["lab5"] = StaticText(_("https://github.com/norhap"))

		if path.exists('/var/volatile/tmp/cam.check.log'):
			file = open('/var/volatile/tmp/cam.check.log')
			softcamlog = file.read()
			file.close()
		else:
			softcamlog = ""
		self["list"] = ScrollLabel(str(softcamlog))
		self["setupActions"] = ActionMap(["SetupActions", "ColorActions", "DirectionActions"], {
			"cancel": self.cancel,
			"ok": self.cancel,
			"up": self["list"].pageUp,
			"down": self["list"].pageDown
		}, -2)

	def cancel(self):
		self.close()


class SoftcamAutoPoller:
	"""Automatically Poll SoftCam"""

	def __init__(self):
		self.timer = eTimer()
		self.Console = Console()
		if not path.exists("/usr/softcams"):
			mkdir("/usr/softcams", 0o755)
		if not path.exists("/etc/scce"):
			mkdir("/etc/scce", 0o755)
		if not path.exists("/etc/tuxbox/config"):
			mkdir("/etc/tuxbox/config", 0o755)
		if not path.islink("/var/tuxbox"):
			symlink("/etc/tuxbox", "/var/tuxbox")
		if not path.exists("/usr/keys"):
			mkdir("/usr/keys", 0o755)
		if not path.islink("/var/keys"):
			symlink("/usr/keys", "/var/keys")
		if not path.islink("/etc/keys"):
			symlink("/usr/keys", "/etc/keys")
		if not path.islink("/var/scce"):
			symlink("/etc/scce", "/var/scce")

	def start(self):
		if self.softcam_check not in self.timer.callback:
			self.timer.callback.append(self.softcam_check)
		self.timer.startLongTimer(1)

	def stop(self):
		if self.softcam_check in self.timer.callback:
			self.timer.callback.remove(self.softcam_check)
		self.timer.stop()

	def softcam_check(self):
		now = int(time())
		if path.exists("/tmp/SoftcamRuningCheck.tmp"):
			remove("/tmp/SoftcamRuningCheck.tmp")

		if config.softcammanager.softcams_autostart:
			Components.Task.job_manager.AddJob(self.createCheckJob())

		if config.softcammanager.softcamtimerenabled.value:
			# 			print "[SoftcamManager] Timer Check Enabled"
			output = open("/tmp/cam.check.log", "a")
			now = datetime.now()
			output.write(now.strftime("%Y-%m-%d %H:%M") + ": Timer Check Enabled\n")
			output.close()
			self.timer.startLongTimer(config.softcammanager.softcamtimer.value * 60)
		else:
			output = open("/tmp/cam.check.log", "a")
			now = datetime.now()
			output.write(now.strftime("%Y-%m-%d %H:%M") + ": Timer Check Disabled\n")
			output.close()
			# 			print "[SoftcamManager] Timer Check Disabled"
			softcamautopoller.stop()

	def createCheckJob(self):
		job = Components.Task.Job(_("SoftcamCheck"))

		task = Components.Task.PythonTask(job, _("Checking softcams..."))
		task.work = self.JobStart
		task.weighting = 1

		return job

	def JobStart(self):
		self.autostartcams = config.softcammanager.softcams_autostart.value
		if path.exists("/tmp/cam.check.log"):
			if path.getsize("/tmp/cam.check.log") > 40000:
				fh = open("/tmp/cam.check.log", "rb+")
				fh.seek(-40000, 2)
				data = fh.read()
				fh.seek(0)  # rewind
				fh.write(data)
				fh.truncate()
				fh.close()

		if path.exists("/etc/CCcam.cfg"):
			f = open("/etc/CCcam.cfg", "r")
			logwarn = ""
			for line in f.readlines():
				if line.find("LOG WARNINGS") != -1:
					parts = line.strip().split()
					logwarn = parts[2]
					if logwarn.find(":") >= 0:
						logwarn = logwarn.replace(":", "")
					if logwarn == "":
						logwarn = parts[3]
				else:
					logwarn = ""
			if path.exists(logwarn):
				if path.getsize(logwarn) > 40000:
					fh = open(logwarn, "rb+")
					fh.seek(-40000, 2)
					data = fh.read()
					fh.seek(0)  # rewind
					fh.write(data)
					fh.truncate()
					fh.close()
			f.close()

		for softcamcheck in self.autostartcams:
			softcamcheck = softcamcheck.replace("/usr/softcams/", "")
			softcamcheck = softcamcheck.replace("\n", "")
			if softcamcheck.endswith(".sh"):
				if path.exists("/tmp/SoftcamsDisableCheck"):
					file = open("/tmp/SoftcamsDisableCheck")
					data = file.read()
					file.close()
				else:
					data = ""
				if data.find(softcamcheck) < 0:
					if path.exists("/tmp/SoftcamsScriptsRunning"):
						file = open("/tmp/SoftcamsScriptsRunning")
						data = file.read()
						file.close()
						if data.find(softcamcheck) < 0:
							fileout = open("/tmp/SoftcamsScriptsRunning", "a")
							line = softcamcheck + "\n"
							fileout.write(line)
							fileout.close()
							print("[SoftcamManager] Starting " + softcamcheck)
							self.Console.ePopen("/usr/softcams/" + softcamcheck + " start")
					else:
						fileout = open("/tmp/SoftcamsScriptsRunning", "w")
						line = softcamcheck + "\n"
						fileout.write(line)
						fileout.close()
						print("[SoftcamManager] Starting " + softcamcheck)
						self.Console.ePopen("/usr/softcams/" + softcamcheck + " start")
			else:
				if path.exists("/tmp/SoftcamsDisableCheck"):
					file = open("/tmp/SoftcamsDisableCheck")
					data = file.read()
					file.close()
				else:
					data = ""
				if data.find(softcamcheck) < 0:
					softcamcheck_process = str(ProcessList().named(softcamcheck)).strip("[]")
					if softcamcheck_process != "":
						if path.exists("/tmp/frozen"):
							remove("/tmp/frozen")
						if path.exists("/tmp/status.html"):
							remove("/tmp/status.html")
						if path.exists("/tmp/index.html"):
							remove("/tmp/index.html")
						print("[SoftcamManager] " + softcamcheck + " already running")
						output = open("/tmp/cam.check.log", "a")
						now = datetime.now()
						output.write(now.strftime("%Y-%m-%d %H:%M") + ": " + softcamcheck + " running OK\n")
						output.close()
						if softcamcheck.lower().startswith("oscam"):
							if path.exists("/tmp/status.html"):
								remove("/tmp/status.html")
							port = ""
							if path.exists('/etc/tuxbox/config/oscam/oscam.conf'):
								oscamconf = '/etc/tuxbox/config/oscam/oscam.conf'
							elif path.exists('/etc/tuxbox/config/ncam/ncam.conf'):
								oscamconf = '/etc/tuxbox/config/ncam/ncam.conf'
							elif path.exists('/etc/tuxbox/config/oscam-emu/oscam.conf'):
								oscamconf = '/etc/tuxbox/config/oscam-emu/oscam.conf'
							elif path.exists('/etc/tuxbox/config/oscam-smod/oscam.conf'):
								oscamconf = '/etc/tuxbox/config/oscam-smod/oscam.conf'
							f = open(oscamconf, 'r')
							for line in f.readlines():
								if line.find("httpport") != -1:
									port = re.sub(r"\D", "", line)
							f.close()
							print("[SoftcamManager] Checking if " + softcamcheck + " is frozen")
							if port == "":
								port = "16000"
							system("wget http://127.0.0.1:" + port + "/status.html -O /tmp/status.html &> /tmp/frozen")
							f = open("/tmp/frozen")
							frozen = f.read()
							f.close()
							if frozen.find("Unauthorized") != -1 or frozen.find("Authorization Required") != -1 or frozen.find("Forbidden") != -1 or frozen.find("Connection refused") != -1 or frozen.find("100%") != -1 or path.exists("/tmp/status.html"):
								print("[SoftcamManager] " + softcamcheck + " is responding like it should")
								output = open("/tmp/cam.check.log", "a")
								now = datetime.now()
								output.write(now.strftime("%Y-%m-%d %H:%M") + ": " + softcamcheck + " is responding like it should\n")
								output.close()
							else:
								print("[SoftcamManager] " + softcamcheck + " is frozen, Restarting...")
								output = open("/tmp/cam.check.log", "a")
								now = datetime.now()
								output.write(now.strftime("%Y-%m-%d %H:%M") + ": " + softcamcheck + " is frozen, Restarting...\n")
								output.close()
								print("[SoftcamManager] Stopping " + softcamcheck)
								output = open("/tmp/cam.check.log", "a")
								now = datetime.now()
								output.write(now.strftime("%Y-%m-%d %H:%M") + ": AutoStopping: " + softcamcheck + "\n")
								output.close()
								self.Console.ePopen("killall -9 " + softcamcheck)
								self.Console.ePopen("ps.procps | grep softcams | grep -v grep | awk 'NR==1' | awk '{print $5}'| awk  -F'[/]' '{print $4}' > /tmp/oscamRuningCheck.tmp")
								file = open("/tmp/oscamRuningCheck.tmp")
								print("[SoftcamManager] Starting " + softcamcheck)
								output = open("/tmp/cam.check.log", "a")
								now = datetime.now()
								output.write(now.strftime("%Y-%m-%d %H:%M") + ": AutoStarting: " + softcamcheck + "\n")
								output.close()
								self.Console.ePopen('sh /etc/init.d/softcam.%s start' % softcamcheck)

						elif softcamcheck.lower().startswith("cccam"):
							if path.exists("/tmp/index.html"):
								remove("/tmp/index.html")
							allow = "no"
							port = ""
							f = open("/etc/CCcam.cfg", "r")
							for line in f.readlines():
								if line.find("ALLOW WEBINFO") != -1:
									if not line.startswith("#"):
										parts = line.replace("ALLOW WEBINFO", "")
										parts = parts.replace(":", "")
										parts = parts.replace(" ", "")
										parts = parts.strip().split()
										if parts[0].startswith("yes"):
											allow = parts[0]
								if line.find("WEBINFO LISTEN PORT") != -1:
									port = re.sub(r"\D", "", line)
							f.close()
							if allow.lower().find("yes") != -1:
								print("[SoftcamManager] Checking if " + softcamcheck + " is frozen")
								if port == "":
									port = "16001"
								system("wget http://127.0.0.1:" + port + " -O /tmp/index.html &> /tmp/frozen")
								f = open("/tmp/frozen")
								frozen = f.read()
								f.close()
								if frozen.find("Unauthorized") != -1 or frozen.find("Authorization Required") != -1 or frozen.find("Forbidden") != -1 or frozen.find("Connection refused") != -1 or frozen.find("100%") != -1 or path.exists("/tmp/index.html"):
									print("[SoftcamManager] " + softcamcheck + " is responding like it should")
									output = open("/tmp/cam.check.log", "a")
									now = datetime.now()
									output.write(now.strftime("%Y-%m-%d %H:%M") + ": ' + softcamcheck + ' is responding like it should\n")
									output.close()
								else:
									print("[SoftcamManager] " + softcamcheck + " is frozen, Restarting...")
									output = open("/tmp/cam.check.log", "a")
									now = datetime.now()
									output.write(now.strftime("%Y-%m-%d %H:%M") + ": " + softcamcheck + " is frozen, Restarting...\n")
									output.close()
									print("[SoftcamManager] Stopping " + softcamcheck)
									self.Console.ePopen("killall -9 " + softcamcheck)
									print("[SoftcamManager] Starting " + softcamcheck)
									self.Console.ePopen("ulimit -s 1024;/usr/softcams/" + softcamcheck)
							elif allow.lower().find("no") != -1:
								print("[SoftcamManager] Telnet info not allowed, can not check if frozen")
								output = open("/tmp/cam.check.log", "a")
								now = datetime.now()
								output.write(now.strftime("%Y-%m-%d %H:%M") + ":  Webinfo info not allowed, can not check if frozen,\n\tplease enable 'ALLOW WEBINFO: YES'\n")
								output.close()
							else:
								print("[SoftcamManager] Webinfo info not setup, please enable 'ALLOW WEBINFO= YES'")
								output = open("/tmp/cam.check.log", "a")
								now = datetime.now()
								output.write(now.strftime("%Y-%m-%d %H:%M") + ":  Telnet info not setup, can not check if frozen,\n\tplease enable 'ALLOW WEBINFO: YES'\n")
								output.close()

					elif softcamcheck_process == "":
						print("[SoftcamManager] Couldn't find " + softcamcheck + " running, Starting " + softcamcheck)
						output = open("/tmp/cam.check.log", "a")
						now = datetime.now()
						output.write(now.strftime("%Y-%m-%d %H:%M") + ": Couldn't find " + softcamcheck + " running, Starting " + softcamcheck + "\n")
						output.close()
						if softcamcheck.lower().startswith("oscam"):
							system("ps.procps | grep softcams | grep -v grep | awk 'NR==1' | awk '{print $5}'| awk  -F'[/]' '{print $4}' > /tmp/softcamRuningCheck.tmp")
							file = open("/tmp/softcamRuningCheck.tmp")
							system('sh /etc/init.d/softcam.%s start' % softcamcheck)
							remove("/tmp/softcamRuningCheck.tmp")
						if softcamcheck.lower().startswith("ncam"):
							self.Console.ePopen("ps.procps | grep softcams | grep -v grep | awk 'NR==1' | awk '{print $5}'| awk  -F'[/]' '{print $4}' > /tmp/softcamRuningCheck.tmp")
							file = open("/tmp/softcamRuningCheck.tmp")
							system('sh /etc/init.d/softcam.%s start' % softcamcheck)
							remove("/tmp/softcamRuningCheck.tmp")
						if softcamcheck.lower().startswith("sbox"):
							system("ulimit -s 1024;/usr/softcams/" + softcamcheck)
						if softcamcheck.lower().startswith("gbox"):
							system("ulimit -s 1024;/usr/softcams/" + softcamcheck)
							system("start-stop-daemon --start --quiet --background --exec /usr/bin/gbox")
						if softcamcheck.lower().startswith('wicardd') or softcamcheck.startswith('mgcamd') or softcamcheck.startswith('CCcam'):
							system('sh /etc/init.d/softcam.%s start' % softcamcheck)
						# if softcamcheck.startswith('mgcamd'): # code no increse RAM for MGcamd.
						# mgcamd = str(ProcessList().named("mgcamd")).strip("[]")
						# if not mgcamd:
						# self.Console.ePopen('sh /etc/init.d/softcam.%s start' % softcamcheck)
						# if softcamcheck.startswith('CCcam'):
						# self.Console.ePopen('sh /etc/init.d/softcam.%s start' % softcamcheck)
