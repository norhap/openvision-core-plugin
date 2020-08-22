#!/usr/bin/python
# -*- coding: utf-8 -*-
from __future__ import print_function
from Components.config import config
from enigma import eEPGCache, eDVBDB
from xml.dom import minidom
import urllib
import urllib2
import re
import os
#############################DOWNLOADER
from Components.Network import iNetwork
from time import localtime, time, strftime, mktime
import socket
import threading
import urllib
import urllib2

from xml.dom import minidom

MAX_THREAD_COUNT = 40
###########################IPSCAN
from Components.Console import Console
from Components.config import config

import os

mountstate = False
mounthost = None
#####################IPBOXMOUNT
from Screens.Wizard import Wizard
from Components.ActionMap import ActionMap
from Components.Pixmap import Pixmap
from Components.Sources.Boolean import Boolean
from Components.config import config

from Tools import Directories

from enigma import eTimer
#############################MENU
from Screens.Screen import Screen
from Screens.MessageBox import MessageBox
from Screens.Standby import TryQuitMainloop

from Components.ActionMap import ActionMap
from Components.Button import Button
from Components.ConfigList import ConfigListScreen
from Components.config import config, getConfigListEntry, ConfigSubsection, ConfigInteger, ConfigYesNo, ConfigText
from Components.Sources.Boolean import Boolean
from Components.Sources.StaticText import StaticText

from enigma import eTimer
#############################ABOUT
from Components.Label import Label

mountstate = False
mounthost = None

def getValueFromNode(event, key):
	tmp = event.getElementsByTagName(key)[0].firstChild
	if (tmp):
		return str(tmp.nodeValue)

	return ""

class GBIpboxWizard(Wizard):

	skin = """
		<screen position="0,0" size="720,576" flags="wfNoBorder" >
			<widget name="text"
					position="153,40"
					size="340,300"
					font="Regular;22" />

			<widget source="list"
					render="Listbox"
					position="53,340"
					size="440,180"
					scrollbarMode="showOnDemand" >

				<convert type="StringList" />

			</widget>

			<widget name="config"
					position="53,340"
					zPosition="1"
					size="440,180"
					transparent="1"
					scrollbarMode="showOnDemand" />

			<ePixmap pixmap="skin_default/buttons/button_red.png"
					 position="40,225"
					 zPosition="0"
					 size="15,16"
					 transparent="1"
					 alphatest="on" />

			<widget name="languagetext"
					position="55,225"
					size="95,30"
					font="Regular;18" />

			<widget name="wizard"
					pixmap="skin_default/wizard.png"
					position="40,50"
					zPosition="10"
					size="110,174"
					alphatest="on" />

			<widget name="rc"
					pixmaps="skin_default/rc0.png,skin_default/rc1.png,skin_default/rc2.png"
					position="500,50"
					zPosition="10"
					size="154,500"
					alphatest="on" />

			<widget name="arrowdown"
					pixmap="skin_default/arrowdown.png"
					position="-100,-100"
					zPosition="11"
					size="37,70"
					alphatest="on" />

			<widget name="arrowdown2"
					pixmap="skin_default/arrowdown.png"
					position="-100,-100"
					zPosition="11"
					size="37,70"
					alphatest="on" />

			<widget name="arrowup"
					pixmap="skin_default/arrowup.png"
					position="-100,-100"
					zPosition="11"
					size="37,70"
					alphatest="on" />

			<widget name="arrowup2"
					pixmap="skin_default/arrowup.png"
					position="-100,-100"
					zPosition="11"
					size="37,70"
					alphatest="on" />

			<widget source="VKeyIcon"
					render="Pixmap"
					pixmap="skin_default/buttons/key_text.png"
					position="40,260"
					zPosition="0"
					size="35,25"
					transparent="1"
					alphatest="on" >

				<convert type="ConditionalShowHide" />

			</widget>

			<widget name="HelpWindow"
					pixmap="skin_default/buttons/key_text.png"
					position="310,435"
					zPosition="1"
					size="1,1"
					transparent="1"
					alphatest="on" />

		</screen>"""

	def __init__(self, session):
		self.xmlfile = Directories.resolveFilename(Directories.SCOPE_PLUGINS, "SystemPlugins/Vision/gbipboxwizard.xml")

		Wizard.__init__(self, session)

		self.setTitle(_('GBIpbox Client'))

		self.skinName = ["StartWizard"]

		self['myactions'] = ActionMap(["MenuActions"],
									  {
									  'menu': self.Menu,
									  'exit': self.exit,
									  }, -1)

	def Menu(self, session=None, **kwargs):
		self.session.openWithCallback(GBIpboxTimer, GBIpboxMenu, GBIpboxMount)

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
		scanner = GBIpboxScan(self.session)
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

			mount = GBIpboxMount(self.session)
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
		downloader = GBIpboxDownloader(self.session)
		try:
			downloader.download()
			self.currStep = self.getStepWithID('end')
		except Exception as e:
			print(str(e))
			self.currStep = self.getStepWithID('nodownload')
		self.currStep += 1
		self.updateValues()
#############################IPSCAM
class ScanHost(threading.Thread):
	def __init__(self, ipaddress, port):
		threading.Thread.__init__(self)
		self.ipaddress = ipaddress
		self.port = port
		self.isopen = False

	def run(self):
		serverip  = socket.gethostbyname(self.ipaddress)

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

class GBIpboxScan:
	def __init__(self, session):
		self.session = session

	def scan(self):
		print("[GBIpboxClient] network scan started")
		devices = []
		for key in iNetwork.ifaces:
			if iNetwork.ifaces[key]['up']:
				devices += self.scanNetwork(iNetwork.ifaces[key]['ip'], iNetwork.ifaces[key]['netmask'])

		print("[GBIpboxClient] network scan completed. Found " + str(len(devices)) + " devices")
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
					temp[i-1] += 1
			ip_range.append(".".join(map(str, temp)))

		return ip_range

	def getNetSize(self, netmask):
		binary_str = ''
		for octet in netmask:
			binary_str += bin(int(octet))[2:].zfill(8)
		return len(binary_str.rstrip('0'))

	def getBoxName(self, ipaddress):
		try:
			httprequest = urllib2.urlopen('http://' + ipaddress + '/web/about', timeout = 5)
			xmldoc = minidom.parseString(httprequest.read())
			return xmldoc.getElementsByTagName('e2model')[0].firstChild.nodeValue
		except Exception:
			pass
		return None

	def scanNetwork(self, ipaddress, subnet):
		print("[GBIpboxClient] scan interface with ip address", ipaddress, "and subnet", subnet)
		cidr = self.getNetSize(subnet)

		startip = []
		for i in range(4):
			startip.append(int(ipaddress[i]) & int(subnet[i]))

		endip = list(startip)
		brange = 32 - cidr
		for i in range(brange):
			endip[3 - i/8] = endip[3 - i/8] + (1 << (i % 8))

		if startip[0] == 0:	# if start with 0, we suppose the interface is not properly configured
			print("[GBIpboxClient] your start ip address seem invalid. Skip interface scan.")
			return []

		startip[3] += 1
		endip[3] -= 1

		print("[GBIpboxClient] scan from ip", startip, "to", endip)

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
				print("[GBIpboxClient] device with ip " + scanhost.ipaddress + " listen on port 80, check if it's enigma2")
				boxname = self.getBoxName(scanhost.ipaddress)
				if boxname:
					print("[GBIpboxClient] found " + boxname + " on ip " + scanhost.ipaddress)
					devices.append((str(boxname), scanhost.ipaddress))
				else:
					print("[GBIpboxClient] no enigma2 found. Skip host")
		return devices
###################IPBOXMOUNT
class GBIpboxMount:
	def __init__(self, session):
		self.session = session
		self.console = Console()
		if os.path.exists('/media/hdd') or os.system('mount |grep -i /media/hdd') == 0:
			self.mountpoint = '/media/net/IpBox'
		else:
			self.mountpoint = '/media/hdd'
		self.share = 'Harddisk'

	def automount(self):
		global mountstate
		global mounthost
		mountstate = False
		mounthost = None
		if config.ipboxclient.mounthdd.value:
			if self.isMountPoint(self.mountpoint):
				if not self.umount(self.mountpoint):
					print('Cannot umount ' + self.mounpoint)
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

	def umount(self, path = None):
		return os.system('umount ' + path) == 0

	def mount(self, ip, share, path):
		try:
			os.makedirs(path)
		except Exception:
			pass
		return os.system('mount -t cifs -o rw,nolock,noatime,noserverino,iocharset=utf8,vers=2.0,username=guest,password= //' + ip + '/' + share + ' ' + path) == 0
###############################################MENU
class GBIpboxMenu(Screen, ConfigListScreen):
	skin = """
		<screen name="GBIpboxMenu" position="360,150" size="560,400">
			<widget name="config"
					position="10,10"
					zPosition="3"
					size="540,270"
					scrollbarMode="showOnDemand"
					transparent="1">
			</widget>

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
		self.timerinstance = timerinstance
		self.remotetimer_old = config.ipboxclient.remotetimers.value
		Screen.__init__(self, session)
		ConfigListScreen.__init__(self, self.list)

		self.setTitle(_('GBIpbox Client'))

		self["VKeyIcon"] = Boolean(False)
		self["text"] = StaticText(_('NOTE: the remote HDD feature require samba installed on server box.'))
		self["key_red"] = Button(_('Cancel'))
		self["key_green"] = Button(_('Save'))
		self["key_yellow"] = Button(_('Scan'))
		self["key_blue"] = Button(_('About'))
		self["actions"] = ActionMap(["OkCancelActions", "ColorActions"],
		{
			"cancel": self.keyCancel,
			"red": self.keyCancel,
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
			self.list.append(getConfigListEntry(_("Username"), config.ipboxclient.username))
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

		mount = GBIpboxMount(self.session)
		mount.remount()

		self.messagebox = self.session.open(MessageBox, _('Please wait while download is in progress.\nNOTE: If you have parental control enabled on remote box, the local settings will be overwritten.'), MessageBox.TYPE_INFO, enable_input = False)
		self.timer = eTimer()
		self.timer.callback.append(self.download)
		self.timer.start(100)

	def keyCancel(self):
		for x in self["config"].list:
			x[1].cancel()
		GBIpboxMenu.instance = self.session.open(TryQuitMainloop, 3)

	def keyAbout(self):
		self.session.open(GBIpboxAbout)

	def keyScan(self):
		self.messagebox = self.session.open(MessageBox, _('Please wait while scan is in progress.\nThis operation may take a while'), MessageBox.TYPE_INFO, enable_input = False)
		self.timer = eTimer()
		self.timer.callback.append(self.scan)
		self.timer.start(100)

	def scan(self):
		self.timer.stop()
		scanner = GBIpboxScan(self.session)
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
			self.session.open(MessageBox, _("No devices found"), type = MessageBox.TYPE_ERROR)

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

			mount = GBIpboxMount(self.session)
			mount.remount()

			self.populateMenu()

	def download(self):
		self.timer.stop()
		downloader = GBIpboxDownloader(self.session)
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
			self.session.openWithCallback(self.restart, MessageBox, _("To apply new settings, you need to reboot your STB. Do you want reboot it now?"), type = MessageBox.TYPE_YESNO)
		else:
			self.session.openWithCallback(self.close, MessageBox, _("Download completed"), type = MessageBox.TYPE_INFO)

	def downloadError(self):
		self.timer.stop()
		self.session.open(MessageBox, _("Cannot download data. Please check your configuration"), type = MessageBox.TYPE_ERROR)

class GBIpboxTimer:
	def __init__(self, session):
		self.session = session
		self.skinName = "GBIpboxMenu"
		self.keys = "GBIpboxMenu"
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
					scheduled_time += 24*3600
					while (int(scheduled_time)-30) < now:
						scheduled_time += 24*3600
				elif config.ipboxclient.repeattype.value == "weekly":
					scheduled_time += 7*24*3600
					while (int(scheduled_time)-30) < now:
						scheduled_time += 7*24*3600
				elif config.ipboxclient.repeattype.value == "monthly":
					scheduled_time += 30*24*3600
					while (int(scheduled_time)-30) < now:
						scheduled_time += 30*24*3600
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
			downloader = GBIpboxDownloader(self.session)
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

class GBIpboxDownloader:
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

		print("[GBIpboxClient] web interface url: " + baseurl)
		print("[GBIpboxClient] streaming url: " + streamingurl)

		for stype in [ "tv", "radio" ]:
			print("[GBIpboxClient] download " + stype + " bouquets from " + baseurl)
			bouquets = self.downloadBouquets(baseurl, stype)
			print("[GBIpboxClient] save " + stype + " bouquets from " + streamingurl)
			self.saveBouquets(bouquets, streamingurl, '/etc/enigma2/bouquets.' + stype)

		print("[GBIpboxClient] reload bouquets")
		self.reloadBouquets()

		print("[GBIpboxClient] sync EPG")
		self.downloadEPG(baseurl)

		print("[GBIpboxClient] sync parental control")
		self.downloadParentalControl(baseurl)

		print("[GBIpboxClient] sync is done!")

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
		print("[GBIpboxClient] download bouquets from " + baseurl + '/web/bouquets?stype=' + stype)
		xmldoc = minidom.parseString(httprequest.read())
		services = xmldoc.getElementsByTagName('e2service')
		for service in services:
			bouquet = {}
			bouquet['reference'] = getValueFromNode(service, 'e2servicereference')
			bouquet['name'] = getValueFromNode(service, 'e2servicename')
			bouquet['services'] = [];

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
		print("[GBIpboxClient] streamurl " + streamingurl)
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
		print("[GBIpboxClient] reading remote EPG location ...")
		filename = self.getEPGLocation(baseurl)
		if not filename:
			print("[GBIpboxClient] error downloading remote EPG location. Skip EPG sync.")
			return

		print("[GBIpboxClient] remote EPG found at " + filename)

		print("[GBIpboxClient] dump remote EPG to epg.dat")
		httprequest = urllib2.urlopen(baseurl + '/web/saveepg')

		httprequest = urllib2.urlopen(baseurl + '/file?action=download&file=' + urllib.quote(filename))
		data = httprequest.read()
		if not data:
			print("[GBIpboxClient] cannot download remote EPG. Skip EPG sync.")
			return

		try:
			epgfile = open(config.misc.epgcache_filename.value, "w")
		except Exception:
			print("[GBIpboxClient] cannot save EPG. Skip EPG sync.")
			return

		epgfile.write(data)
		epgfile.close()

		print("[GBIpboxClient] reload EPG")
		epgcache = eEPGCache.getInstance()
		epgcache.load()

	def downloadParentalControl(self, baseurl):
		print("[GBIpboxClient] reading remote parental control status ...")

		if self.getParentalControlEnabled(baseurl):
			print("[GBIpboxClient] parental control enabled")
			config.ParentalControl.servicepinactive.value = True
			config.ParentalControl.servicepinactive.save()
			print("[GBIpboxClient] reding pin status ...")
			pinstatus = self.getParentalControlPinState(baseurl)
			pin = self.getParentalControlPin(baseurl)
			print("[GBIpboxClient] pin status is setted to " + str(pinstatus))
			config.ParentalControl.servicepinactive.value = pinstatus
			config.ParentalControl.servicepinactive.save()
			config.ParentalControl.servicepin[0].value = pin
			config.ParentalControl.servicepin[0].save()
			print("[GBIpboxClient] reading remote parental control type ...")
			stype = self.getParentalControlType(baseurl)
			print("[GBIpboxClient] parental control type is " + stype)
			config.ParentalControl.type.value = stype
			config.ParentalControl.type.save()
			print("[GBIpboxClient] download parental control services list")
			services = self.downloadParentalControlBouquets(baseurl)
			print("[GBIpboxClient] save parental control services list")
			parentalfile = open("/etc/enigma2/" + stype, "w")
			for service in services:
				parentalfile.write(service['reference'] + "\n")
			parentalfile.close()
			print("[GBIpboxClient] reload parental control")
			from Components.ParentalControl import parentalControl
			parentalControl.open()
		else:
			print("[GBIpboxClient] parental control disabled - do nothing")

class GBIpboxAbout(Screen):
	skin = """
			<screen position="360,150" size="560,400">
				<widget name="about"
						position="10,10"
						size="540,340"
						font="Regular;22"
						zPosition="1" />
			</screen>"""

	def __init__(self, session):
		Screen.__init__(self, session)

		self.setTitle(_('GBIpbox Client About'))
		about = "GBIpbox Client 1.0""\n"

		about += "(c) 2014 Impex-Sat Gmbh & Co.KG\n\n"
		about += "Written by Sandro Cavazzoni <sandro@skanetwork.com>"

		self['about'] = Label(about)
		self["actions"] = ActionMap(["SetupActions"],
		{
			"cancel": self.keyCancel
		})

	def keyCancel(self):
		self.close()