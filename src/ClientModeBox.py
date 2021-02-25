#!/usr/bin/python
# -*- coding: utf-8 -*-
from __future__ import print_function
from Screens.WizardLanguage import WizardLanguage
from enigma import eEPGCache, eDVBDB
from xml.dom import minidom
import urllib
import urllib2
import re
import os
from Components.Network import iNetwork
from time import localtime, time, strftime, mktime, ctime
import socket
import threading
from Components.Console import Console
from Components.Pixmap import Pixmap
from Components.Sources.Boolean import Boolean
from Tools import Directories
from Tools.Directories import fileHas, resolveFilename, SCOPE_PLUGINS
from Screens.Screen import Screen
from Screens.MessageBox import MessageBox
from Screens.Standby import TryQuitMainloop
from Components.ActionMap import ActionMap
from Components.Button import Button
from Components.ConfigList import ConfigListScreen
from Components.config import config, ConfigBoolean, getConfigListEntry, ConfigSubsection, ConfigInteger, ConfigYesNo, ConfigText, ConfigClock, ConfigSelection
from Components.Sources.StaticText import StaticText
from enigma import eTimer
from Components.Label import Label
from bisect import insort
from Components.TimerSanityCheck import TimerSanityCheck
from RecordTimer import RecordTimerEntry, AFTEREVENT
from ServiceReference import ServiceReference
from timer import TimerEntry
from . import _, PluginLanguageDomain

mountstate = False
mounthost = None
MAX_THREAD_COUNT = 40
timerinstance = None

config.ipboxclient = ConfigSubsection()
config.ipboxclient.host = ConfigText(default="", fixed_size=False)
config.ipboxclient.port = ConfigInteger(default=80, limits=(1, 65535))
config.ipboxclient.streamport = ConfigInteger(default=8001, limits=(1, 65535))
config.ipboxclient.auth = ConfigYesNo(default=False)
config.ipboxclient.firstconf = ConfigYesNo(default=False)
config.ipboxclient.username = ConfigText(default="", fixed_size=False)
config.ipboxclient.password = ConfigText(default="", fixed_size=False)
config.ipboxclient.schedule = ConfigYesNo(default=False)
config.ipboxclient.scheduletime = ConfigClock(default=0) # 1:00
config.ipboxclient.repeattype = ConfigSelection(default="daily", choices=[("daily", _("Daily")), ("weekly", _("Weekly")), ("monthly", _("Monthly"))])
config.ipboxclient.mounthdd = ConfigYesNo(default=False)
config.ipboxclient.remotetimers = ConfigYesNo(default=False)


def getValueFromNode(event, key):
	tmp = event.getElementsByTagName(key)[0].firstChild
	if (tmp):
		return str(tmp.nodeValue)

	return ""


class ClientModeBoxWizard(WizardLanguage):

	skin = """
		<screen name="ClientModeBoxWizard" position="center,center" size="720,576" title="ClientModeBoxWizard" >
			<widget name="text"
					position="65,40"
					size="640,100"
					font="Regular;24" />

			<widget source="list"
					render="Listbox"
					position="65,160"
					size="640,220"
					font="Regular;24"
					scrollbarMode="showOnDemand" >
				<convert type="StringList" />
			</widget>

			<widget name="config"
					position="65,160"
					zPosition="1"
					size="440,220"
					transparent="1"
					font="Regular;24"
					scrollbarMode="showOnDemand" />

			<widget name="step"
					position="65,470"
					zPosition="1"
					size="440,40"
					transparent="1" />

			<widget name="stepslider"
					borderWidth="1"
					position="65,468"
					zPosition="1"
					size="440,40"
					transparent="1" />

			<ePixmap pixmap="skin_default/buttons/button_red.png"
					 position="35,523"
					 zPosition="0"
					 size="15,16"
					 transparent="1"
					 alphatest="blend" />

			<widget name="languagetext"
					position="65,520"
					size="300,30"
					font="Regular;18" />
		</screen>"""

	def __init__(self, session):
		self.xmlfile = Directories.resolveFilename(Directories.SCOPE_PLUGINS, "SystemPlugins/Vision/clientmodebox.xml")
		WizardLanguage.__init__(self, session)
		self.setTitle(_('Vision Client Mode Box'))
		self.skinName = ["ClientModeBoxWizard"]
		self["lab1"] = StaticText(_("OpenVision"))
		self["lab2"] = StaticText(_("Lets define enigma2 once more"))
		self["lab3"] = StaticText(_("Report problems to:"))
		self["lab4"] = StaticText(_("https://openvision.tech"))
		self["lab5"] = StaticText(_("Sources are available at:"))
		self["lab6"] = StaticText(_("https://github.com/OpenVisionE2"))
		self['myactions'] = ActionMap(["MenuActions"],
									  {
									  'menu': self.Menu,
									  'exit': self.exit,
									  }, -1)

	def Menu(self, session=None, **kwargs):
		self.session.open(ClientModeBoxMenu, PluginLanguageDomain)

	def exit(self):
		self.close(True)

	def getTranslation(self, text):
		return _(text)

	def scan(self):
		self.timer = eTimer()
		self.timer.callback.append(self.doscan)
		self.timer.start(100)

	def doscan(self):
		self.timer.stop()
		scanner = ClientModeBoxScan(self.session)
		self.scanresults = scanner.scan()
		if self.scanresults and len(self.scanresults) > 0:
			self.currStep = self.getStepWithID('choose')
		else:
			self.currStep = self.getStepWithID('nodevices')
		self.currStep += 1
		self.updateValues()

	def getScanList(self):
		devices = []
		for result in self.scanresults:
			devices.append((result[0] + ' (' + result[1] + ')', result[1]))

		devices.append((_('Cancel'), 'cancel'))
		return devices

	def selectionMade(self, result):
		selecteddevice = None
		if result != 'cancel':
			for device in self.scanresults:
				if device[1] == result:
					selecteddevice = device
		if selecteddevice:
			config.ipboxclient.host.value = selecteddevice[1]
			config.ipboxclient.host.save()
			config.ipboxclient.port.value = 80
			config.ipboxclient.port.save()
			config.ipboxclient.streamport.value = 8001
			config.ipboxclient.streamport.save()
			config.ipboxclient.auth.value = False
			config.ipboxclient.auth.save()
			config.ipboxclient.firstconf.value = True
			config.ipboxclient.firstconf.save()

			mount = ClientModeBoxMount(self.session)
			mount.remount()

			self.currStep = self.getStepWithID('download')
		else:
			self.currStep = self.getStepWithID('welcome')

	def download(self):
		self.timer = eTimer()
		self.timer.callback.append(self.dodownload)
		self.timer.start(100)

	def dodownload(self):
		self.timer.stop()
		downloader = ClientModeBoxDownloader(self.session)
		try:
			downloader.download()
			self.currStep = self.getStepWithID('end')
		except Exception as e:
			print(str(e))
			self.currStep = self.getStepWithID('nodownload')
		self.currStep += 1
		self.updateValues()


class ScanHost(threading.Thread):
	def __init__(self, ipaddress, port):
		threading.Thread.__init__(self)
		self.ipaddress = ipaddress
		self.port = port
		self.isopen = False

	def run(self):
		serverip = socket.gethostbyname(self.ipaddress)

		try:
			sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
			sock.settimeout(10)
			result = sock.connect_ex((serverip, self.port))
			sock.close()
			self.isopen = result == 0

		except socket.gaierror:
			self.isopen = False

		except socket.error:
			self.isopen = False


class ClientModeBoxScan:
	def __init__(self, session):
		self.session = session

	def scan(self):
		print("[ClientModeBox] network scan started")
		devices = []
		for key in iNetwork.ifaces:
			if iNetwork.ifaces[key]['up']:
				devices += self.scanNetwork(iNetwork.ifaces[key]['ip'], iNetwork.ifaces[key]['netmask'])

		print("[ClientModeBox] network scan completed. Found " + str(len(devices)) + " devices")
		return devices

	def ipRange(self, start_ip, end_ip):
		temp = start_ip
		ip_range = []

		ip_range.append(".".join(map(str, start_ip)))
		while temp != end_ip:
			start_ip[3] += 1
			for i in (3, 2, 1):
				if temp[i] == 256:
					temp[i] = 0
					temp[i - 1] += 1
			ip_range.append(".".join(map(str, temp)))

		return ip_range

	def getNetSize(self, netmask):
		binary_str = ''
		for octet in netmask:
			binary_str += bin(int(octet))[2:].zfill(8)
		return len(binary_str.rstrip('0'))

	def getBoxName(self, ipaddress):
		try:
			httprequest = urllib2.urlopen('http://' + ipaddress + '/web/about', timeout=5)
			xmldoc = minidom.parseString(httprequest.read())
			return xmldoc.getElementsByTagName('e2model')[0].firstChild.nodeValue
		except Exception:
			pass
		return None

	def scanNetwork(self, ipaddress, subnet):
		print("[ClientModeBox] scan interface with ip address", ipaddress, "and subnet", subnet)
		cidr = self.getNetSize(subnet)

		startip = []
		for i in range(4):
			startip.append(int(ipaddress[i]) & int(subnet[i]))

		endip = list(startip)
		brange = 32 - cidr
		for i in range(brange):
			endip[3 - i / 8] = endip[3 - i / 8] + (1 << (i % 8))

		if startip[0] == 0:
			print("[ClientModeBox] your start ip address seem invalid. Skip interface scan.")
			return []

		startip[3] += 1
		endip[3] -= 1

		print("[ClientModeBox] scan from ip", startip, "to", endip)

		threads = []
		threads_completed = []
		for iptoscan in self.ipRange(startip, endip):
			if len(threads) >= MAX_THREAD_COUNT:
				scanhost = threads.pop(0)
				scanhost.join()
				threads_completed.append(scanhost)

			scanhost = ScanHost(iptoscan, 80)
			scanhost.start()
			threads.append(scanhost)

		for scanhost in threads:
			scanhost.join()
			threads_completed.append(scanhost)

		devices = []
		for scanhost in threads_completed:
			if scanhost.isopen:
				print("[ClientModeBox] device with ip " + scanhost.ipaddress + " listen on port 80, check if it's enigma2")
				boxname = self.getBoxName(scanhost.ipaddress)
				if boxname:
					print("[ClientModeBox] found " + boxname + " on ip " + scanhost.ipaddress)
					devices.append((str(boxname), scanhost.ipaddress))
				else:
					print("[ClientModeBox] no enigma2 found. Skip host")
		return devices


class ClientModeBoxMount:
	def __init__(self, session):
		self.session = session
		self.console = Console()
		if os.path.exists('/media/hdd') or os.system('mount |grep -i /media/hdd') == 0:
			self.mountpoint = '/media/net/hddboxserver'
		else:
			self.mountpoint = '/media/hdd'
		self.share = '/mnt/hdd'

	def automount(self):
		global mountstate
		global mounthost
		mountstate = False
		mounthost = None
		if config.ipboxclient.mounthdd.value:
			if self.isMountPoint(self.mountpoint):
				if not self.umount(self.mountpoint):
					print('Cannot umount ')
					return

			if not self.mount(config.ipboxclient.host.value, self.share, self.mountpoint):
				print('Cannot mount ' + config.ipboxclient.host.value + '/' + self.share + ' to ' + self.mountpoint)
			else:
				mountstate = True
				mounthost = config.ipboxclient.host.value

	def remount(self):
		global mountstate
		global mounthost
		if mountstate and not config.ipboxclient.mounthdd.value:
			self.umount(self.mountpoint)
			mountstate = False
		elif not mountstate and config.ipboxclient.mounthdd.value:
			self.automount()
		elif mountstate and config.ipboxclient.mounthdd.value != mounthost:
			self.automount()

	def isMountPoint(self, path):
		return os.system('mountpoint ' + path) == 0

	def umount(self, path=None):
		return os.system('umount ' + path) == 0

	def mount(self, ip, share, path):
	    if not fileHas("/etc/fstab", ":/mnt/hdd"):
		try:
			os.makedirs(path)
		except Exception:
			pass
		return os.system('mount -t nfs' + ' ' + ip + ':' + '/' + share + ' ' + path + ' ' + '&&' + ' ' + 'echo -e' + ' ' + '"' + ip + ':' + share + ' ' + path + ' ' + 'nfs nolock,rsize=8192,wsize=8192' + ' ' + '\n"' + ' ' + '>>' + ' ' + '/etc/fstab') == 0


class ClientModeBoxMenu(Screen, ConfigListScreen):
	skin = """
		<screen name="ClientModeBoxMenu" position="100,100" size="560,400">
			<widget name="config"
					position="10,10"
					zPosition="3"
					size="540,270"
					scrollbarMode="showOnDemand"
					transparent="1"/>

			<widget source="text"
					render="Label"
					position="10,290"
					size="540,60"
					font="Regular;20" />

			<widget name="key_red"
					position="0,360"
					size="140,40"
					valign="center"
					halign="center"
					zPosition="5"
					transparent="1"
					foregroundColor="white"
					font="Regular;18" />

			<widget name="key_green"
					position="140,360"
					size="140,40"
					valign="center"
					halign="center"
					zPosition="5"
					transparent="1"
					foregroundColor="white"
					font="Regular;18" />

			<widget name="key_yellow"
					position="280,360"
					size="140,40"
					valign="center"
					halign="center"
					zPosition="5"
					transparent="1"
					foregroundColor="white"
					font="Regular;18" />

			<widget name="key_blue"
					position="420,360"
					size="140,40"
					valign="center"
					halign="center"
					zPosition="5"
					transparent="1"
					foregroundColor="white"
					font="Regular;18" />

			<ePixmap name="red"
					 pixmap="skin_default/buttons/red.png"
					 position="0,360"
					 size="140,40"
					 zPosition="4"
					 transparent="1"
					 alphatest="on" />

			<ePixmap name="green"
					 pixmap="skin_default/buttons/green.png"
					 position="140,360"
					 size="140,40"
					 zPosition="4"
					 transparent="1"
					 alphatest="on" />

			<ePixmap name="yellow"
					 pixmap="skin_default/buttons/yellow.png"
					 position="280,360"
					 size="140,40"
					 zPosition="4"
					 transparent="1"
					 alphatest="on" />

			<ePixmap name="blue"
					 pixmap="skin_default/buttons/blue.png"
					 position="420,360"
					 size="140,40"
					 zPosition="4"
					 transparent="1"
					 alphatest="on" />
		</screen>"""

	def __init__(self, session, timerinstance):
		self.session = session
		self.list = []
		self.timerinstance = ClientModeBoxTimer(self.session)
		self.remotetimer_old = config.ipboxclient.remotetimers.value
		Screen.__init__(self, session)
		ConfigListScreen.__init__(self, self.list)
		self.setTitle(_('Vision Client Mode Box'))
		self["lab1"] = StaticText(_("OpenVision"))
		self["lab2"] = StaticText(_("Lets define enigma2 once more"))
		self["lab3"] = StaticText(_("Report problems to:"))
		self["lab4"] = StaticText(_("https://openvision.tech"))
		self["lab5"] = StaticText(_("Sources are available at:"))
		self["lab6"] = StaticText(_("https://github.com/OpenVisionE2"))

		self["VKeyIcon"] = Boolean(False)
		self["text"] = StaticText(_('Important: Do not enable OpenWebif authentication on server, neither in this Setup.'))
		self["key_red"] = Button(_('Cancel'))
		self["key_green"] = Button(_('Save'))
		self["key_yellow"] = Button(_('Scan'))
		self["key_blue"] = Button(_('About'))
		self["actions"] = ActionMap(["OkCancelActions", "ColorActions"],
		{
			"cancel": self.keyCancel,
			"red": self.closeRecursive,
			"green": self.keySave,
			"yellow": self.keyScan,
			"blue": self.keyAbout
		}, -2)

		self.populateMenu()

		if not config.ipboxclient.firstconf.value:
			self.timer = eTimer()
			self.timer.callback.append(self.scanAsk)
			self.timer.start(100)

	def exit(self):
		self.close(True)

	def scanAsk(self):
		self.timer.stop()
		self.session.openWithCallback(self.scanConfirm, MessageBox, _("Do you want to scan for a server?"), MessageBox.TYPE_YESNO)

	def scanConfirm(self, confirmed):
		if confirmed:
			self.keyScan()

	def populateMenu(self):
		self.list = []
		self.list.append(getConfigListEntry(_("Host"), config.ipboxclient.host))
		self.list.append(getConfigListEntry(_("HTTP port"), config.ipboxclient.port))
		self.list.append(getConfigListEntry(_("Streaming port"), config.ipboxclient.streamport))
		self.list.append(getConfigListEntry(_("Authentication"), config.ipboxclient.auth))
		if config.ipboxclient.auth.value:
			self.list.append(getConfigListEntry(_("Default username (root)"), config.ipboxclient.username))
			self.list.append(getConfigListEntry(_("Password"), config.ipboxclient.password))
		self.list.append(getConfigListEntry(_("Use remote HDD"), config.ipboxclient.mounthdd))
		self.list.append(getConfigListEntry(_("Use remote timers"), config.ipboxclient.remotetimers))
		self.list.append(getConfigListEntry(_("Schedule sync"), config.ipboxclient.schedule))
		if config.ipboxclient.schedule.getValue():
			self.list.append(getConfigListEntry(_("Time of sync to start"), config.ipboxclient.scheduletime))
			self.list.append(getConfigListEntry(_("Repeat how often"), config.ipboxclient.repeattype))

		self["config"].list = self.list
		self["config"].l.setList(self.list)

	def keyLeft(self):
		ConfigListScreen.keyLeft(self)
		self.populateMenu()

	def keyRight(self):
		ConfigListScreen.keyRight(self)
		self.populateMenu()

	def keySave(self):
		for x in self["config"].list:
			x[1].save()
		config.ipboxclient.firstconf.value = True
		config.ipboxclient.firstconf.save()
		if self.timerinstance:
			self.timerinstance.refreshScheduler()

		mount = ClientModeBoxMount(self.session)
		mount.remount()

		self.messagebox = self.session.open(MessageBox, _('Please wait while download is in progress.\nNote: If you have parental control enabled on remote box, the local settings will be overwritten.'), MessageBox.TYPE_INFO, enable_input=False)
		self.timer = eTimer()
		self.timer.callback.append(self.download)
		self.timer.start(100)

	def closeRecursive(self):
		self.close(True)

	def keyAbout(self):
		self.session.open(ClientModeBoxAbout)

	def keyScan(self):
		self.messagebox = self.session.open(MessageBox, _('Please wait while scan is in progress.\nThis operation may take a while'), MessageBox.TYPE_INFO, enable_input=False)
		self.timer = eTimer()
		self.timer.callback.append(self.scan)
		self.timer.start(100)

	def scan(self):
		self.timer.stop()
		scanner = ClientModeBoxScan(self.session)
		self.scanresults = scanner.scan()
		self.messagebox.close()
		self.timer = eTimer()
		self.timer.callback.append(self.parseScanResults)
		self.timer.start(100)

	def parseScanResults(self):
		self.timer.stop()
		if len(self.scanresults) > 0:
			menulist = []
			for result in self.scanresults:
				menulist.append((result[0] + ' (' + result[1] + ')', result))
			menulist.append((_('Cancel'), None))
			message = _("Choose your main device")
			self.session.openWithCallback(self.scanCallback, MessageBox, message, list=menulist)
		else:
			self.session.open(MessageBox, _("No devices found"), type=MessageBox.TYPE_ERROR)

	def scanCallback(self, result):
		if (result):
			config.ipboxclient.host.value = result[1]
			config.ipboxclient.host.save()
			config.ipboxclient.port.value = 80
			config.ipboxclient.port.save()
			config.ipboxclient.streamport.value = 8001
			config.ipboxclient.streamport.save()
			config.ipboxclient.auth.value = False
			config.ipboxclient.auth.save()
			config.ipboxclient.firstconf.value = True
			config.ipboxclient.firstconf.save()

			mount = ClientModeBoxMount(self.session)
			mount.remount()

			self.populateMenu()

	def download(self):
		self.timer.stop()
		downloader = ClientModeBoxDownloader(self.session)
		try:
			downloader.download()
			self.messagebox.close()
			self.timer = eTimer()
			self.timer.callback.append(self.downloadCompleted)
			self.timer.start(100)
		except Exception as e:
			print(str(e))
			self.messagebox.close()
			self.timer = eTimer()
			self.timer.callback.append(self.downloadError)
			self.timer.start(100)

	def restart(self, response):
		if response:
			self.session.open(TryQuitMainloop, 3)
		else:
			self.close()

	def downloadCompleted(self):
		self.timer.stop()
		if self.remotetimer_old != config.ipboxclient.remotetimers.value:
			self.session.openWithCallback(self.restart, MessageBox, _("To apply new settings, you need to restart GUI your STB. Do you want restart it now?"), type=MessageBox.TYPE_YESNO)
		else:
			self.session.openWithCallback(self.close, MessageBox, _("Download completed"), type=MessageBox.TYPE_INFO)

	def downloadError(self):
		self.timer.stop()
		self.session.open(MessageBox, _("Cannot download data. Please check your configuration"), type=MessageBox.TYPE_ERROR)


class ClientModeBoxDownloader:
	def __init__(self, session):
		self.session = session

	def download(self):
		baseurl = "http://"
		if config.ipboxclient.auth.value:
			baseurl += config.ipboxclient.username.value
			baseurl += ":"
			baseurl += config.ipboxclient.password.value
			baseurl += "@"

		baseurl += config.ipboxclient.host.value
		baseurl += ":"

		streamingurl = baseurl

		baseurl += str(config.ipboxclient.port.value)
		streamingurl += str(config.ipboxclient.streamport.value)

		print("[ClientModeBox] web interface url: " + baseurl)
		print("[ClientModeBox] streaming url: " + streamingurl)

		for stype in ["tv", "radio"]:
			print("[ClientModeBox] Download " + stype + " bouquets from " + baseurl)
			bouquets = self.downloadBouquets(baseurl, stype)
			print("[ClientModeBox] save " + stype + " bouquets from " + streamingurl)
			self.saveBouquets(bouquets, streamingurl, '/etc/enigma2/bouquets.' + stype)

		print("[ClientModeBox] reload bouquets")
		self.reloadBouquets()

		print("[ClientModeBox] sync EPG")
		self.downloadEPG(baseurl)

		print("[ClientModeBox] sync parental control")
		self.downloadParentalControl(baseurl)

		print("[ClientModeBox] sync is done!")

	def getSetting(self, baseurl, key):
		httprequest = urllib2.urlopen(baseurl + '/web/settings')
		xmldoc = minidom.parseString(httprequest.read())
		settings = xmldoc.getElementsByTagName('e2setting')
		for setting in settings:
			if getValueFromNode(setting, 'e2settingname') == key:
				return getValueFromNode(setting, 'e2settingvalue')

		return None

	def getEPGLocation(self, baseurl):
		return self.getSetting(baseurl, 'config.misc.epgcache_filename')

	def getParentalControlEnabled(self, baseurl):
		return self.getSetting(baseurl, 'config.ParentalControl.servicepinactive') == 'true'

	def getParentalControlType(self, baseurl):
		value = self.getSetting(baseurl, 'config.ParentalControl.type')
		if not value:
			value = 'blacklist'
		return value

	def getParentalControlPinState(self, baseurl):
		return self.getSetting(baseurl, 'config.ParentalControl.servicepinactive') == 'true'

	def getParentalControlPin(self, baseurl):
		value = self.getSetting(baseurl, 'config.ParentalControl.servicepin.0')
		if not value:
			value = "0000"
		return int(value)

	def downloadParentalControlBouquets(self, baseurl):
		bouquets = []
		httprequest = urllib2.urlopen(baseurl + '/web/parentcontrollist')
		xmldoc = minidom.parseString(httprequest.read())
		services = xmldoc.getElementsByTagName('e2service')
		for service in services:
			bouquet = {}
			bouquet['reference'] = getValueFromNode(service, 'e2servicereference')
			bouquet['name'] = getValueFromNode(service, 'e2servicename')

			bouquets.append(bouquet)

		return bouquets

	def downloadBouquets(self, baseurl, stype):
		bouquets = []
		httprequest = urllib2.urlopen(baseurl + '/web/bouquets?stype=' + stype)
		print("[ClientModeBox] download bouquets from " + baseurl + '/web/bouquets?stype=' + stype)
		xmldoc = minidom.parseString(httprequest.read())
		services = xmldoc.getElementsByTagName('e2service')
		for service in services:
			bouquet = {}
			bouquet['reference'] = getValueFromNode(service, 'e2servicereference')
			bouquet['name'] = getValueFromNode(service, 'e2servicename')
			bouquet['services'] = []

			httprequest = urllib2.urlopen(baseurl + '/web/getservices?' + urllib.urlencode({'sRef': bouquet['reference']}) + '&hidden=1')
			xmldoc2 = minidom.parseString(httprequest.read())
			services2 = xmldoc2.getElementsByTagName('e2service')
			for service2 in services2:
				ref = ""
				tmp = getValueFromNode(service2, 'e2servicereference')
				cnt = 0
				for x in tmp:
					ref += x
					if x == ':':
						cnt += 1
					if cnt == 10:
						break

				bouquet['services'].append({
					'reference': ref,
					'name': getValueFromNode(service2, 'e2servicename')
				})

			bouquets.append(bouquet)

		return bouquets

	def saveBouquets(self, bouquets, streamingurl, destinationfile):
		bouquetsfile = open(destinationfile, "w")
		bouquetsfile.write("#NAME Bouquets (TV)" + "\n")
		print("[ClientModeBox] streamurl " + streamingurl)
		for bouquet in bouquets:
			pattern = r'"([A-Za-z0-9_\./\\-]*)"'
			m = re.search(pattern, bouquet['reference'])
			if not m:
				continue

			filename = m.group().strip("\"")
			bouquetsfile.write("#SERVICE " + bouquet['reference'] + "\n")
			outfile = open("/etc/enigma2/" + filename, "w")
			outfile.write("#NAME " + bouquet['name'] + "\n")
			for service in bouquet['services']:
				tmp = service['reference'].split(':')
				isDVB = False
				isStreaming = False
				url = ""

				if len(tmp) > 1 and tmp[0] == '1' and tmp[1] == '0':
					if len(tmp) > 10 and tmp[10].startswith('http%3a//'):
						isStreaming = True
					else:
						isDVB = True
						url = streamingurl + "/" + service['reference']

				if isDVB:
					outfile.write("#SERVICE " + service['reference'] + urllib.quote(url) + ":" + service['name'] + "\n")
				elif isStreaming:
					outfile.write("#SERVICE " + service['reference'] + "\n")
				else:
					outfile.write("#SERVICE " + service['reference'] + "\n")
					outfile.write("#DESCRIPTION " + service['name'] + "\n")
			outfile.close()
		bouquetsfile.close()

	def reloadBouquets(self):
		db = eDVBDB.getInstance()
		db.reloadServicelist()
		db.reloadBouquets()

	def downloadEPG(self, baseurl):
		print("[ClientModeBox] reading remote EPG location ...")
		filename = self.getEPGLocation(baseurl)
		if not filename:
			print("[ClientModeBox] error downloading remote EPG location. Skip EPG sync.")
			return

		print("[ClientModeBox] remote EPG found at " + filename)

		print("[ClientModeBox] dump remote EPG to epg.dat")
		httprequest = urllib2.urlopen(baseurl + '/web/saveepg')

		httprequest = urllib2.urlopen(baseurl + '/file?action=download&file=' + urllib.quote(filename))
		data = httprequest.read()
		if not data:
			print("[ClientModeBox] cannot download remote EPG. Skip EPG sync.")
			return

		try:
			epgfile = open(config.misc.epgcache_filename.value, "w")
		except Exception:
			print("[ClientModeBox] cannot save EPG. Skip EPG sync.")
			return

		epgfile.write(data)
		epgfile.close()

		print("[ClientModeBox] reload EPG")
		epgcache = eEPGCache.getInstance()
		epgcache.load()

	def downloadParentalControl(self, baseurl):
		print("[ClientModeBox] reading remote parental control status ...")

		if self.getParentalControlEnabled(baseurl):
			print("[ClientModeBox] parental control enabled")
			config.ParentalControl.servicepinactive.value = True
			config.ParentalControl.servicepinactive.save()
			print("[ClientModeBox] reding pin status ...")
			pinstatus = self.getParentalControlPinState(baseurl)
			pin = self.getParentalControlPin(baseurl)
			print("[ClientModeBox] pin status is setted to " + str(pinstatus))
			config.ParentalControl.servicepinactive.value = pinstatus
			config.ParentalControl.servicepinactive.save()
			config.ParentalControl.servicepin[0].value = pin
			config.ParentalControl.servicepin[0].save()
			print("[ClientModeBox] reading remote parental control type ...")
			stype = self.getParentalControlType(baseurl)
			print("[ClientModeBox] parental control type is " + stype)
			config.ParentalControl.type.value = stype
			config.ParentalControl.type.save()
			print("[ClientModeBox] download parental control services list")
			services = self.downloadParentalControlBouquets(baseurl)
			print("[ClientModeBox] save parental control services list")
			parentalfile = open("/etc/enigma2/" + stype, "w")
			for service in services:
				parentalfile.write(service['reference'] + "\n")
			parentalfile.close()
			print("[ClientModeBox] reload parental control")
			from Components.ParentalControl import parentalControl
			parentalControl.open()
		else:
			print("[ClientModeBox] parental control disabled - do nothing")


class ClientModeBoxAbout(Screen):
	skin = """
			<screen position="100,100" size="560,400">
				<widget name="about"
						position="10,10"
						size="540,340"
						font="Regular;22"
						zPosition="1" />
			</screen>"""

	def __init__(self, session):
		Screen.__init__(self, session)
		self["lab1"] = StaticText(_("OpenVision"))
		self["lab2"] = StaticText(_("Lets define enigma2 once more"))
		self["lab3"] = StaticText(_("Report problems to:"))
		self["lab4"] = StaticText(_("https://openvision.tech"))
		self["lab5"] = StaticText(_("Sources are available at:"))
		self["lab6"] = StaticText(_("https://github.com/OpenVisionE2"))

		self.setTitle(_('Vision Client Mode Box'))

		self['about'] = Label(_("Client Mode Box: If you want to exit Client Mode and have a backup with your original settings. You can restore from blue button on Vision Backup Manager."))
		self["actions"] = ActionMap(["SetupActions"],
		{
			"cancel": self.keyCancel
		})

	def keyCancel(self):
		self.close()


class ClientModeBoxTimer:
	def __init__(self, session):
		self.session = session
		self.ipboxdownloadtimer = eTimer()
		self.ipboxdownloadtimer.callback.append(self.onIpboxDownloadTimer)

		self.ipboxpolltimer = eTimer()
		self.ipboxpolltimer.timeout.get().append(self.onIpboxPollTimer)

		self.refreshScheduler()

	def onIpboxPollTimer(self):
		self.ipboxpolltimer.stop()
		self.scheduledtime = self.prepareTimer()

	def getTodayScheduledTime(self):
		backupclock = config.ipboxclient.scheduletime.value
		now = localtime(time())
		return int(mktime((now.tm_year, now.tm_mon, now.tm_mday, backupclock[0], backupclock[1], 0, now.tm_wday, now.tm_yday, now.tm_isdst)))

	def prepareTimer(self):
		self.ipboxdownloadtimer.stop()
		scheduled_time = self.getTodayScheduledTime()
		now = int(time())
		if scheduled_time > 0:
			if scheduled_time < now:
				if config.ipboxclient.repeattype.value == "daily":
					scheduled_time += 24 * 3600
					while (int(scheduled_time) - 30) < now:
						scheduled_time += 24 * 3600
				elif config.ipboxclient.repeattype.value == "weekly":
					scheduled_time += 7 * 24 * 3600
					while (int(scheduled_time) - 30) < now:
						scheduled_time += 7 * 24 * 3600
				elif config.ipboxclient.repeattype.value == "monthly":
					scheduled_time += 30 * 24 * 3600
					while (int(scheduled_time) - 30) < now:
						scheduled_time += 30 * 24 * 3600
			next = scheduled_time - now
			self.ipboxdownloadtimer.startLongTimer(next)
		else:
			scheduled_time = -1
		return scheduled_time

	def onIpboxDownloadTimer(self):
		self.ipboxdownloadtimer.stop()
		now = int(time())
		wake = self.getTodayScheduledTime()
		if wake - now < 60:
			downloader = ClientModeBoxDownloader(self.session)
			try:
				downloader.download()
			except Exception as e:
				print(str(e))
		self.scheduledtime = self.prepareTimer()

	def refreshScheduler(self):
		now = int(time())
		if config.ipboxclient.schedule.value:
			if now > 1262304000:
				self.scheduledtime = self.prepareTimer()
			else:
				self.scheduledtime = 0
				self.ipboxpolltimer.start(36000)
		else:
			self.scheduledtime = 0
			self.ipboxpolltimer.stop()


class ClientModeBoxRemoteTimer():
	_timer_list = []
	_processed_timers = []

	on_state_change = []

	last_update_ts = 0

	def __init__(self):
		pass

	@property
	def timer_list(self):
		if self.last_update_ts + 30 < time():
			self.getTimers()
		return self._timer_list

	@timer_list.setter
	def timer_list(self, value):
		self._timer_list = value

	@timer_list.deleter
	def timer_list(self):
		del self._timer_list

	@property
	def processed_timers(self):
		if self.last_update_ts + 30 < time():
			self.getTimers()
		return self._processed_timers

	@processed_timers.setter
	def processed_timers(self, value):
		self._processed_timers = value

	@processed_timers.deleter
	def processed_timers(self):
		del self._processed_timers

	def getTimers(self):
		self._timer_list = []
		self._processed_timers = []

		baseurl = self.getBaseUrl()

		print("[ClientModeBoxRemoteTimer] get remote timer list")

		try:
			httprequest = urllib2.urlopen(baseurl + '/web/timerlist')
			xmldoc = minidom.parseString(httprequest.read())
			timers = xmldoc.getElementsByTagName('e2timer')
			for timer in timers:
				serviceref = ServiceReference(getValueFromNode(timer, 'e2servicereference'))
				begin = int(getValueFromNode(timer, 'e2timebegin'))
				end = int(getValueFromNode(timer, 'e2timeend'))
				name = getValueFromNode(timer, 'e2name')
				description = getValueFromNode(timer, 'e2description')
				eit = int(getValueFromNode(timer, 'e2eit'))
				disabled = int(getValueFromNode(timer, 'e2disabled'))
				justplay = int(getValueFromNode(timer, 'e2justplay'))
				afterevent = int(getValueFromNode(timer, 'e2afterevent'))
				repeated = int(getValueFromNode(timer, 'e2repeated'))
				location = getValueFromNode(timer, 'e2location')
				tags = getValueFromNode(timer, 'e2tags').split(" ")

				entry = RecordTimerEntry(serviceref, begin, end, name, description, eit, disabled, justplay, afterevent, dirname=location, tags=tags, descramble=1, record_ecm=0, isAutoTimer=0, always_zap=0)
				entry.repeated = repeated

				entry.orig = RecordTimerEntry(serviceref, begin, end, name, description, eit, disabled, justplay, afterevent, dirname=location, tags=tags, descramble=1, record_ecm=0, isAutoTimer=0, always_zap=0)
				entry.orig.repeated = repeated

				if entry.shouldSkip() or entry.state == TimerEntry.StateEnded or (entry.state == TimerEntry.StateWaiting and entry.disabled):
					insort(self._processed_timers, entry)
				else:
					insort(self._timer_list, entry)
		except Exception as e:
			print("[ClientModeBoxRemoteTimer]", e)

		self.last_update_ts = time()

	def getBaseUrl(self):
		baseurl = "http://"
		if config.ipboxclient.auth.value:
			baseurl += config.ipboxclient.username.value
			baseurl += ":"
			baseurl += config.ipboxclient.password.value
			baseurl += "@"

		baseurl += config.ipboxclient.host.value
		baseurl += ":"
		baseurl += str(config.ipboxclient.port.value)
		return baseurl

	def getNextRecordingTime(self):
		return -1

	def getNextZapTime(self):
		return -1

	def isNextRecordAfterEventActionAuto(self):
		return False

	def isInTimer(self, eventid, begin, duration, service):
		returnValue = None
		type = 0
		time_match = 0
		isAutoTimer = False
		bt = None
		end = begin + duration
		refstr = ":".join(str(service).split(":")[:10]) + ':'
		for x in self._timer_list:
			if x.isAutoTimer == 1:
				isAutoTimer = True
			else:
				isAutoTimer = False
			check = x.service_ref.ref.toString() == refstr
			if check:
				timer_end = x.end
				type_offset = 0
				if x.justplay:
					type_offset = 5
					if (timer_end - x.begin) <= 1:
						timer_end += 60
				if x.always_zap:
					type_offset = 10

				if x.repeated != 0:
					if bt is None:
						bt = localtime(begin)
						et = localtime(end)
						bday = bt.tm_wday
						begin2 = bday * 1440 + bt.tm_hour * 60 + bt.tm_min
						end2 = et.tm_wday * 1440 + et.tm_hour * 60 + et.tm_min
					if x.repeated & (1 << bday):
						xbt = localtime(x.begin)
						xet = localtime(timer_end)
						xbegin = bday * 1440 + xbt.tm_hour * 60 + xbt.tm_min
						xend = bday * 1440 + xet.tm_hour * 60 + xet.tm_min
						if xend < xbegin:
							xend += 1440
						if begin2 < xbegin <= end2:
							if xend < end2: # recording within event
								time_match = (xend - xbegin) * 60
								type = type_offset + 3
							else:           # recording last part of event
								time_match = (end2 - xbegin) * 60
								type = type_offset + 1
						elif xbegin <= begin2 <= xend:
							if xend < end2: # recording first part of event
								time_match = (xend - begin2) * 60
								type = type_offset + 4
							else:           # recording whole event
								time_match = (end2 - begin2) * 60
								type = type_offset + 2
				else:
					if begin < x.begin <= end:
						if timer_end < end: # recording within event
							time_match = timer_end - x.begin
							type = type_offset + 3
						else:           # recording last part of event
							time_match = end - x.begin
							type = type_offset + 1
					elif x.begin <= begin <= timer_end:
						if timer_end < end: # recording first part of event
							time_match = timer_end - begin
							type = type_offset + 4
						else:           # recording whole event
							time_match = end - begin
							type = type_offset + 2
				if time_match:
					if type in (2, 7, 12): # When full recording do not look further
						returnValue = (time_match, [type], isAutoTimer)
						break
					elif returnValue:
						if type not in returnValue[1]:
							returnValue[1].append(type)
					else:
						returnValue = (time_match, [type])

		return returnValue

	def record(self, entry, ignoreTSC=False, dosave=True):
		print("[ClientModeBoxRemoteTimer] record ", str(entry))

		entry.service_ref = ServiceReference(":".join(str(entry.service_ref).split(":")[:10]))
		args = urllib.urlencode({
				'sRef': str(entry.service_ref),
				'begin': str(entry.begin),
				'end': str(entry.end),
				'name': entry.name,
				'disabled': str(1 if entry.disabled else 0),
				'justplay': str(1 if entry.justplay else 0),
				'afterevent': str(entry.afterEvent),
				'dirname': str(entry.dirname),
				'tags': " ".join(entry.tags),
				'repeated': str(entry.repeated),
				'description': entry.description
			})

		baseurl = self.getBaseUrl()

		print("[ClientModeBoxRemoteTimer] web interface url: " + baseurl)

		try:
			httprequest = urllib2.urlopen(baseurl + '/web/timeradd?' + args)
			xmldoc = minidom.parseString(httprequest.read())
			status = xmldoc.getElementsByTagName('e2simplexmlresult')[0]
			success = getValueFromNode(status, 'e2state') == "True"
		except Exception as e:
			print("[ClientModeBoxRemoteTimer]", e)
			return None

		self.getTimers()

		if not success:
			timersanitycheck = TimerSanityCheck(self._timer_list, entry)
			if not timersanitycheck.check():
				print("timer conflict detected!")
				print(timersanitycheck.getSimulTimerList())
				return timersanitycheck.getSimulTimerList()

		return None

	def timeChanged(self, entry):
		print("[ClientModeBoxRemoteTimer] timer changed ", str(entry))

		entry.service_ref = ServiceReference(":".join(str(entry.service_ref).split(":")[:10]))
		try:
			args = urllib.urlencode({
					'sRef': str(entry.service_ref),
					'begin': str(entry.begin),
					'end': str(entry.end),
					'channelOld': str(entry.orig.service_ref),
					'beginOld': str(entry.orig.begin),
					'endOld': str(entry.orig.end),
					'name': entry.name,
					'disabled': str(1 if entry.disabled else 0),
					'justplay': str(1 if entry.justplay else 0),
					'afterevent': str(entry.afterEvent),
					'dirname': str(entry.dirname),
					'tags': " ".join(entry.tags),
					'repeated': str(entry.repeated),
					'description': entry.description
				})

			baseurl = self.getBaseUrl()
			httprequest = urllib2.urlopen(baseurl + '/web/timerchange?' + args)
			xmldoc = minidom.parseString(httprequest.read())
			status = xmldoc.getElementsByTagName('e2simplexmlresult')[0]
			success = getValueFromNode(status, 'e2state') == "True"
		except Exception as e:
			print("[ClientModeBoxRemoteTimer]", e)
			return None

		self.getTimers()

		if not success:
			timersanitycheck = TimerSanityCheck(self._timer_list, entry)
			if not timersanitycheck.check():
				print("timer conflict detected!")
				print(timersanitycheck.getSimulTimerList())
				return timersanitycheck.getSimulTimerList()

		return None

	def removeEntry(self, entry):
		print("[ClientModeBoxRemoteTimer] timer remove ", str(entry))

		entry.service_ref = ServiceReference(":".join(str(entry.service_ref).split(":")[:10]))
		args = urllib.urlencode({
				'sRef': str(entry.service_ref),
				'begin': str(entry.begin),
				'end': str(entry.end)
			})

		baseurl = self.getBaseUrl()
		try:
			httprequest = urllib2.urlopen(baseurl + '/web/timerdelete?' + args)
			httprequest.read()
		except Exception as e:
			print("[ClientModeBoxRemoteTimer]", e)
			return

		self.getTimers()

	def isRecording(self):
		isRunning = False
		for timer in self.timer_list:
			if timer.isRunning() and not timer.justplay:
				isRunning = True
		return isRunning

	def saveTimer(self):
		pass

	def shutdown(self):
		pass

	def cleanup(self):
		self.processed_timers = [entry for entry in self.processed_timers if entry.disabled]

	def cleanupDaily(self, days):
		limit = time() - (days * 3600 * 24)
		self.processed_timers = [entry for entry in self.processed_timers if (entry.disabled and entry.repeated) or (entry.end and (entry.end > limit))]
