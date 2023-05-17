import errno
from os import mkdir, remove, rename, statvfs
from os.path import join, exists, realpath
from re import search, sub

from enigma import eTimer

from .__init__ import _

from Components.ActionMap import ActionMap
from Components.Label import Label
from Components.ConfigList import ConfigListScreen
from Components.config import config, getConfigListEntry, ConfigSelection, NoSave
from Components.Console import Console
from Components.Sources.List import List
from Components.Sources.StaticText import StaticText
from Components.SystemInfo import SystemInfo, BRAND, DISPLAYMODEL
from Screens.MessageBox import MessageBox
from Screens.Screen import Screen
from Screens.Standby import QUIT_REBOOT, TryQuitMainloop
from Tools.LoadPixmap import LoadPixmap
from Tools.Directories import SCOPE_GUISKIN, resolveFilename, SCOPE_PLUGINS
from Components.Harddisk import harddiskmanager

partitions = sorted(harddiskmanager.getMountedPartitions(), key=lambda partitions: partitions.device or "")
for parts in partitions:
	partition = join(str(parts.device))
	mount = join(str(parts.mountpoint))

blacklistedDisks = [
	1,  	# RAM disk (/dev/ram0=0, /dev/initrd=250 [250=Initial RAM disk for old systems, new systems use 0])
	7,  	# Loopback devices (/dev/loop0=0)
	31,  	# ROM/flash memory card (/dev/rom0=0, /dev/rrom0=8, /dev/flash0=16, /dev/rflash0=24 [r=Read Only])
	240,  	# ROM/flash memory card (/dev/rom0=0, /dev/rrom0=8, /dev/flash0=16, /dev/rflash0=24 [r=Read Only])
	253,  	# LOCAL/EXPERIMENTAL USE
	254,  	# LOCAL/EXPERIMENTAL USE
	259  	# MMC block devices (/dev/mmcblk0=0, /dev/mmcblk0p1=1, /dev/mmcblk1=8)
]


def readFile(filename):
	try:
		with open(filename, "r") as fd:
			data = fd.read().strip()
	except (IOError, OSError) as err:
		if err.errno != errno.ENOENT:  # No such file or directory.
			print("[MountManager] Error: Failed to read file! ", err)
		data = None
	return data


def getProcPartitions(partitionList):
	partitions = []
	with open("/proc/partitions", "r") as fd:
		for line in fd.readlines():
			line = line.strip()
			if line == "":  # Skip empty lines.
				continue
			(devmajor, devminor, blocks, device) = line.split()
			if devmajor == "major":  # Skip label line.
				continue
			# print "[MountManager] device='%s', devmajor='%s', devminor='%s'." % (device, devmajor, devminor)
			devMajor = int(devmajor)
			if devMajor in blacklistedDisks:  # Ignore all blacklisted devices.
				continue
			if devMajor == 179:
				if not SystemInfo["HasSDnomount"]:  # Only interested in h9/i55/h9combo(+dups) mmc partitions.  h9combo(+dups) uses mmcblk1p[0-3].
					continue
				if SystemInfo["HasH9SD"]:
					if not search("mmcblk0p1", device):  # h9/i55 only mmcblk0p1 mmc partition
						continue
					if SystemInfo["HasMMC"]:  # With h9/i55 reject mmcblk0p1 mmc partition if root device.
						continue
				if SystemInfo["HasSDnomount"][0] and not search("mmcblk1p[0-3]", device):  # h9combo(+dups) uses mmcblk1p[0-3] include
					continue
			if devMajor == 8:
				if not search("sd[a-z][1-9]", device):  # If storage use partitions only.
					continue
				if SystemInfo["HiSilicon"] and exists("/dev/sda4") and search("sd[a][1-4]", device):  # Sf8008 using SDcard for slots ---> exclude
					continue
			if device in partitions:  # If device is already in partition list ignore it.
				continue
			buildPartitionInfo(device, partitionList)
			partitions.append(device)


def buildPartitionInfo(partition, partitionList):
	if search("mmcblk[0-1]p[0-3]", partition):
		device = sub("p[0-9]", "", partition)
	else:
		device = sub("[0-9]", "", partition)
	physicalDevice = realpath(join("/sys/block", device, "device"))

	description = readFile(join(physicalDevice, "model"))
	if description is None:
		description = readFile(join(physicalDevice, "name"))
	if description is None:
		description = _("Device %s") % partition
	description = str(description).replace("\n", "")

	hotplugBuses = ("usb", "mmc", "ata")
	busTranslate = ("usb", "sd", "hdd")
	count = -1
	for bus in hotplugBuses:
		count += 1
		if "/%s" % bus in physicalDevice:
			break
	# print "[MountManager1]bus: %s count : %s" % (bus, count)
	pngType = busTranslate[count]
	name = _("%s: " % pngType.upper())
	name += description

	if exists(resolveFilename(SCOPE_GUISKIN, "visioncore/dev_%s.png" % pngType)):
		mypixmap = resolveFilename(SCOPE_GUISKIN, "visioncore/dev_%s.png" % pngType)
	else:
		mypixmap = resolveFilename(SCOPE_PLUGINS, "SystemPlugins/Vision/images/dev_%s.png" % pngType)

	description = ""
	mediamount = _("None")
	mountpoint = _("None")
	_format = _("unavailable")
	rw = _("None")

	with open("/proc/mounts", "r") as f:
		for line in f.readlines():
			if line.find(partition) != -1:
				parts = line.strip().split()
				mountpoint = parts[1]
				_format = parts[2]
				rw = parts[3]
				break
				continue
	with open("/proc/partitions", "r") as f:
		for line in f.readlines():
			if line.find(partition) != -1:
				parts = line.strip().split()
# Also, map any fuseblk fstype to the real file-system behind it...
# Use blkid to get the info we need....
#
				if _format == 'fuseblk':
					import subprocess
					res = subprocess.run(['blkid', '-sTYPE', '-ovalue', parts[0]], capture_output=True)
					if res.returncode == 0:
						_format = str(res.stdout).strip()
				break
		size = int(parts[2]) # get size partitions
		if size < 1: # is condition ever fulfilled?
			description = _("Size: unavailable")
		if size < 1000 * 1000:
			description = _("Size: %sMB") % str(int(size))
		elif size < 1000 * 1000 * 1000:
			description = _("Size: %sGB") % format(size / (1000 * 1000), '.2f')
		else:
			description = _("Size: %sTB") % format(size / (1000 * 1000 * 1000), '.2f')
	if description != "": # how will this ever return false?
		if SystemInfo["MountManager"]: # called by VISIONDevicesPanel else DeviceMountSetup
			if rw.startswith("rw"): # read/write
				rw = " R/W"
			elif rw.startswith("ro"):
				rw = " R/O"
			else:
				rw = ""
			description += "\t" + _("Mount: ") + mountpoint + "\n" + _("Device: ") + "/dev/" + partition + "\t" + _("Type: ") + _format + rw
			png = LoadPixmap(mypixmap)
			partitionInfo = (name, description, png)
		else:
			Gmedia = [
				("/media/" + device, "/media/" + device),
				("/media/hdd", "/media/hdd"),
				("/media/hdd2", "/media/hdd2"),
				("/media/hdd3", "/media/hdd3"),
				("/media/usb", "/media/usb"),
				("/media/usb2", "/media/usb2"),
				("/media/usb3", "/media/usb3"),
				("/media/sdcard", "/media/sdcard")
			]
			item = NoSave(ConfigSelection(default="/media/%s" % partition, choices=Gmedia))
			if _format == "Linux":
				_format = "ext4"
			else:
				_format = "auto"
			item.value = mediamount.strip()
			text = name + " " + description + " /dev/" + partition
			partitionInfo = getConfigListEntry(text, item, partition, _format)
		partitionList.append(partitionInfo)


class VISIONDevicesPanel(Screen):
	skin = ["""
	<screen position="center,center" size="%d,%d">
		<widget source="list" render="Listbox" position="%d,%d" size="%d,%d" scrollbarMode="showOnDemand">
			<convert type="TemplatedMultiContent">
				{
				"template":
					[
					MultiContentEntryText(pos = (%d, 0), size = (%d, %d), font = 0, flags = RT_HALIGN_LEFT | RT_VALIGN_CENTER, text = 0),
					MultiContentEntryText(pos = (%d, %d), size = (%d, %d), font = 1, flags = RT_HALIGN_LEFT | RT_VALIGN_TOP, text = 1),
					MultiContentEntryPixmapAlphaBlend(pos = (%d, 0), size = (%d, %d), flags = BT_SCALE, png = 2),
					],
				"fonts": [gFont("Regular",%d), gFont("Regular",%d)],
				"itemHeight": %d
				}
			</convert>
		</widget>
		<widget name="lab7" position="%d,%d" size="%d,%d" font="Regular;%d" horizontalAlignment="center" transparent="1" verticalAlignment="center" zPosition="+1" />
		<widget source="key_red" render="Label" position="%d,e-%d" size="%d,%d" backgroundColor="key_red" font="Regular;%d" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" />
		<widget source="key_green" render="Label" position="%d,e-%d" size="%d,%d" backgroundColor="key_green" font="Regular;%d" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" />
		<widget source="key_yellow" render="Label" position="%d,e-%d" size="%d,%d" backgroundColor="key_yellow" font="Regular;%d" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" />
		<widget source="key_blue" render="Label" position="%d,e-%d" size="%d,%d" backgroundColor="key_blue" font="Regular;%d" foregroundColor="key_text" horizontalAlignment="center" verticalAlignment="center" />
	</screen>""",
		640, 495,
		10, 10, 620, 425,
		100, 520, 30,
		120, 30, 500, 50,
		10, 80, 80,
		24, 20,
		80,
		10, 10, 620, 425, 25,
		10, 50, 140, 40, 20,
		160, 50, 140, 40, 20,
		310, 50, 140, 40, 20,
		460, 50, 140, 40, 20
	]

	def __init__(self, session):
		Screen.__init__(self, session)
		self.setTitle(_("Vision Mount Manager"))
		self["lab1"] = StaticText(_("OpenVision"))
		self["lab2"] = StaticText(_("Lets define enigma2 once more"))
		self["lab3"] = StaticText(_("Report problems to:"))
		self["lab4"] = StaticText(_("https://openvision.tech"))
		self["lab5"] = StaticText(_("Sources are available at:"))
		self["lab6"] = StaticText(_("https://github.com/OpenVisionE2"))
		self["lab7"] = Label(_("Please wait while scanning for devices..."))
		if exists(mount):
			size = statvfs(mount)
		else:
			size = statvfs(0)
		free = (size.f_bfree * size.f_frsize) // (1024 * 1024) // 1000
		if harddiskmanager.HDDList():
			self["key_red"] = StaticText("")
			self["key_green"] = StaticText(_("Setup mounts")) if mount != "/" else StaticText("")
			if partition != "None" and free > 0:
				self["key_yellow"] = StaticText(_("Unmount"))
			self["key_blue"] = StaticText(_("Mount")) if mount != "/" else StaticText("")
		else:
			self["key_green"] = StaticText("")
			self["key_yellow"] = StaticText("")
			self["key_blue"] = StaticText("")
		self.onChangedEntry = []
		self.partitionList = []
		self["list"] = List(self.partitionList)
		self["list"].onSelectionChanged.append(self.selectionChanged)
		self["actions"] = ActionMap(["WizardActions", "ColorActions", "MenuActions"], {
			"back": self.close,
			"green": self.setupMounts,
			"red": self.saveMounthdd,
			"yellow": self.unmount,
			"blue": self.mount,
			"menu": self.close
		})
		self.Console = Console()
		self.activityTimer = eTimer()
		self.activityTimer.timeout.get().append(self.findPartitions)
		self.setTimer()

	def selectionChanged(self):
		# print("[MountManager][selectionChanged] self.partitionList=%s" % self.partitionList)
		if len(self.list) == 0:
			return
		sel = self["list"].getCurrent()	# partitionInfo = (name, description, png)
		# print("[MountManager][selectionChanged] sel1=%s sel2=%s" % (sel[0], sel[1]))
		seldev = sel
		for line in sel:
			try:
				line = line.strip()
				if _("Mount: ") in line:
					if line.find("/media/hdd") < 0:
						self["key_red"].setText(_("Use as HDD"))
				else:
					self["key_red"].setText("")
			except Exception:
				pass
		if sel:
			try:
				name = str(sel[0])
				desc = str(sel[1].replace('\t', '  '))
			except Exception:
				name = ""
				desc = ""
		else:
			name = ""
			desc = ""
		for cb in self.onChangedEntry:
			cb(name, desc)

	def setTimer(self, result=None, retval=None, extra_args=None):
		self["lab7"].show()
		self.activityTimer.start(10)

	def findPartitions(self):
		sel = self["list"].getCurrent()
		self.activityTimer.stop()
		self.list = []
		SystemInfo["MountManager"] = True
		getProcPartitions(self.list)
		self["list"].list = self.list
		self["lab7"].setText(_("No device available.")) if mount == "/" else self["lab7"].hide()

	def setupMounts(self):
		sel = self["list"].getCurrent()
		if sel:
			self.session.openWithCallback(self.setTimer, DeviceMountSetup)	# print("[MountManager][setupMounts]")

	def unmount(self):
		if partition == "None":
			return
		sel = self["list"].getCurrent()
		# print("[MountManager][unmount] sel1=%s sel2=%s" % (sel[0], sel[1]))
		if sel:
			des = sel[1]
			des = des.replace("\n", "\t")
			parts = des.strip().split("\t")
			mountp = parts[1].replace(_("Mount: "), "")
			device = parts[2].replace(_("Device: "), "")
			# print("[MountManager][unmount] mountp=%s device=%s" % (mountp, device))
			exitStatus = self.Console.ePopen("umount %s" % mountp)
			if exitStatus == 0:
				self.session.open(MessageBox, _("Partition: %s  Mount: %s unmounted successfully; if all partitions now unmounted you can remove device.") % (device, mountp), MessageBox.TYPE_INFO)
				self.setTimer()
			else:
				# self.session.open(MessageBox, _("Cannot unmount partition '%s'.  Make sure this partition is not in use.  (SWAP, record/timeshift, etc.)") % mountp, MessageBox.TYPE_INFO)
				# return -1
				self.setTimer()

	def mount(self):
		if mount != "/":
			sel = self["list"].getCurrent()
			# print("[MountManager][mount] sel1=%s sel2=%s" % (sel[0], sel[1]))
			if sel:
				des = sel[1]
				des = des.replace("\n", "\t")
				parts = des.strip().split("\t")
				mountp = parts[1].replace(_("Mount: "), "")
				device = parts[2].replace(_("Device: "), "")
				# print("[MountManager][mount] mountp=%s device=%s" % (mountp, device))
				self.Console.ePopen("mount %s" % device)
				self.setTimer()

	def saveMounts(self):
		if len(self["list"].list) < 1:
			return
		sel = self["list"].getCurrent()
		# print("[MountManager][saveMounts] selection=%s" % sel)
		if sel:
			des = sel[1]
			des = des.replace('\n', '\t')
			parts = des.strip().split('\t')
			device = parts[2].replace(_("Device: "), '')
			moremount = sel[1]
			adv_title = moremount != "" and _("Warning, this device is used for more than one mount point!\n") or ""
			message = adv_title + _("Really use and mount %s as HDD ?") % device
			self.session.open(MessageBox, _("This Device is already mounted as HDD."), MessageBox.TYPE_INFO, timeout=10, close_on_any_key=True)

	def addFstab(self, result=None, retval=None, extra_args=None):
		try:
			self.device = extra_args[0]
			self.mountp = extra_args[1]
			self.device_uuid = "UUID=" + str(result).split("UUID=")[1].split(" ")[0].replace('"', '')
			# print("[MountManager1][addFstab1]: device = %s, mountp=%s, UUID=%s" %(self.device, self.mountp, self.device_uuid))
			if not exists(self.mountp):
				mkdir(self.mountp, 0o755)
			open("/etc/fstab.tmp", "w").writelines([l for l in open("/etc/fstab").readlines() if "/media/hdd" not in l])
			rename("/etc/fstab.tmp", "/etc/fstab")
			open("/etc/fstab.tmp", "w").writelines([l for l in open("/etc/fstab").readlines() if self.device not in l])
			rename("/etc/fstab.tmp", "/etc/fstab")
			open("/etc/fstab.tmp", "w").writelines([l for l in open("/etc/fstab").readlines() if self.device_uuid not in l])
			rename("/etc/fstab.tmp", "/etc/fstab")
			with open("/etc/fstab", "a") as fd:
				line = self.device_uuid + "\t/media/hdd\tauto\tdefaults\t0 0\n"
				fd.write(line)
			fd.close()
			self.Console.ePopen("mount -a", self.setTimer)
		except Exception:
			pass

	def saveMounthdd(self):
		if len(self["list"].list) < 1:
			return
		sel = self["list"].getCurrent()
		seldev = sel
		for line in sel:
			try:
				line = line.strip()
				if _("Mount: ") in line:
					if line.find("/media/hdd") < 0:
						des = sel[1]
						des = des.replace('\n', '\t')
						parts = des.strip().split('\t')
						device = parts[2].replace(_("Device: "), '')
						moremount = sel[1]
						message = _("You may have to press red button again.\nUse %s as HDD ?") % device
						self.session.openWithCallback(self.saveMypointAnswer, MessageBox, message, MessageBox.TYPE_YESNO)
			except Exception:
				pass

	def saveMypointAnswer(self, answer):
		if answer:
			sel = self["list"].getCurrent()
			if sel:
				des = sel[1]
				des = des.replace("\n", "\t")
				parts = des.strip().split("\t")
				self.mountp = parts[1].replace(_("Mount: "), "")
				self.device = parts[2].replace(_("Device: "), "")
				if self.mountp.find("/media/hdd") < 0:
					pass
				else:
					self.session.open(MessageBox, _("This Device is already mounted as HDD."), MessageBox.TYPE_INFO, timeout=6, close_on_any_key=True)
					return
				self.Console.ePopen("[ -e /media/hdd/swapfile ] && swapoff /media/hdd/swapfile")
				self.Console.ePopen("umount /media/hdd")
				try:
					f = open("/proc/mounts", "r")
				except IOError:
					return
				for line in f.readlines():
					if "/media/hdd" in line:
						f.close()
						return
					else:
						pass
				f.close()
				if self.mountp.find("/media/hdd") < 0 and self.mountp != _("/media/hdd"):
					if self.mountp != _("None"):
						self.Console.ePopen("umount " + self.mountp)
					self.Console.ePopen("umount " + self.device)
					self.Console.ePopen("/sbin/blkid | grep " + self.device, self.addFstab, [self.device, self.mountp])
				try:
					f = open("/etc/fstab", "r")
				except IOError:
					return
				for line in f.readlines():
					if "/media/hdd" in line:
						 message = _("The changes need a system restart to take effect.\nRestart your %s %s now?") % (BRAND, DISPLAYMODEL)
						 ybox = self.session.openWithCallback(self.restartBox, MessageBox, message, MessageBox.TYPE_YESNO)
						 ybox.setTitle(_("Restart receiver."))

	def restartBox(self, answer):
		if answer is True:
			self.session.open(TryQuitMainloop, QUIT_REBOOT)
		else:
			self.close()


class DeviceMountSetup(Screen, ConfigListScreen):
	skin = """
	<screen position="center,center" size="640,460">
		<ePixmap pixmap="buttons/red.png" position="25,0" size="140,40" alphaTest="blend"/>
		<ePixmap pixmap="buttons/green.png" position="175,0" size="140,40" alphaTest="blend"/>
		<widget name="key_red" position="25,0" zPosition="1" size="140,40" font="Regular;20" horizontalAlignment="center" verticalAlignment="center" backgroundColor="#9f1313" transparent="1"/>
		<widget name="key_green" position="175,0" zPosition="1" size="140,40" font="Regular;20" horizontalAlignment="center" verticalAlignment="center" backgroundColor="#1f771f" transparent="1"/>
		<widget name="config" position="30,60" size="580,275" scrollbarMode="showOnDemand"/>
		<widget name="lab7" position="30,375" size="580,20" font="Regular;18" horizontalAlignment="center" verticalAlignment="center" backgroundColor="#9f1313"/>
	</screen>"""

	def __init__(self, session):
		Screen.__init__(self, session)
		self.partitionList = []
		ConfigListScreen.__init__(self, self.partitionList)
		self.setTitle(_("Choose where to mount your devices to:"))
		self["lab1"] = StaticText(_("OpenVision"))
		self["lab2"] = StaticText(_("Lets define enigma2 once more"))
		self["lab3"] = StaticText(_("Report problems to:"))
		self["lab4"] = StaticText(_("https://openvision.tech"))
		self["lab5"] = StaticText(_("Sources are available at:"))
		self["lab6"] = StaticText(_("https://github.com/OpenVisionE2"))

		self["key_green"] = Label(_("Save"))
		self["key_red"] = Label(_("Cancel"))
		self["lab7"] = Label()
		self["actions"] = ActionMap(["WizardActions", "ColorActions"], {
			"red": self.close,
			"green": self.saveconfMounts,
			"back": self.close
		})
		self.Console = Console()
		self.activityTimer = eTimer()
		self.activityTimer.timeout.get().append(self.findconfPartitions)
		self.setconfTimer()

	def setconfTimer(self, result=None, retval=None, extra_args=None):
		scanning = _("Scanned devices")
		self["lab7"].setText(scanning)
		self.activityTimer.start(10)

	def findconfPartitions(self):
		self.activityTimer.stop()
		self.partitionList = []
		SystemInfo["MountManager"] = False
		getProcPartitions(self.partitionList)
		self["config"].list = self.partitionList
		self["config"].l.setList(self.partitionList)
		self["lab7"].hide()

	def saveconfMounts(self):
		for x in self["config"].list: # partitionInfo = getConfigListEntry(text, item, partition, _format)
			self.device = x[2]
			self.mountp = x[1].value
			self.type = x[3]
			# print("[MountManager][saveconfMount] mountp=%s device=%s type=%s" % (self.mountp, self.device, self.type))
			self.Console.ePopen("umount %s" % self.device)
			self.Console.ePopen("/sbin/blkid | grep " + self.device + " && opkg list-installed ntfs-3g", self.addconfFstab, [self.device, self.mountp])
		message = _("Updating mount locations...")
		ybox = self.session.openWithCallback(self.delay, MessageBox, message, type=MessageBox.TYPE_INFO, timeout=5, enable_input=False)
		ybox.setTitle(_("Please wait."))

	def delay(self, val):
		message = _("The changes need a system restart to take effect.\nRestart your %s %s now?") % (BRAND, DISPLAYMODEL)
		ybox = self.session.openWithCallback(self.restartBox, MessageBox, message, MessageBox.TYPE_YESNO)
		ybox.setTitle(_("Restart receiver."))

	def addconfFstab(self, result=None, retval=None, extra_args=None):
		# print "[MountManager] Result:", result
		if result:
			self.device = extra_args[0]
			self.mountp = extra_args[1]
			result = str(result)
			uuid = search('UUID=\"([^\"]+)\"', result)
			type = search('TYPE=\"([^\"]+)\"', result)
			if uuid and type:
				self.device_uuid = "UUID=" + uuid.group(1)
				self.device_type = type.group(1)
				# print("[MountManager][addFstab2] device_uuid:%s device_type:%s" % (self.device_uuid, self.device_type))
				if self.device_type.startswith("ext"):
					self.device_type = "auto"
				elif self.device_type.startswith("ntfs") and result.find("ntfs-3g") != -1:
					self.device_type = "ntfs-3g"
				elif self.device_type.startswith("ntfs") and result.find("ntfs-3g") == -1:
					self.device_type = "ntfs"
				if not exists(self.mountp):
					mkdir(self.mountp, 0o755)
				open("/etc/fstab.tmp", "w").writelines([l for l in open("/etc/fstab").readlines() if self.device not in l])
				rename("/etc/fstab.tmp", "/etc/fstab")
				open("/etc/fstab.tmp", "w").writelines([l for l in open("/etc/fstab").readlines() if self.device_uuid not in l])
				rename("/etc/fstab.tmp", "/etc/fstab")
				with open("/etc/fstab", "a") as fd:
					line = self.device_uuid + "\t" + self.mountp + "\t" + self.device_type + "\tdefaults\t0 0\n"
					fd.write(line)

	def restartBox(self, answer):
		if answer is True:
			self.session.open(TryQuitMainloop, QUIT_REBOOT)
		else:
			self.close()
