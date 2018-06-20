from bluepy.btle import Scanner, DefaultDelegate
from miband2 import MiBand2, ActivityDelegate

print "Scanning for nearby MiBands2..."
sc = Scanner()
devs = sc.scan(5)

print "Found {0} devices! Initializing...".format(len(devs)) 
mibands = []
for d in devs:
    mb = MiBand2(d)
    mibands += [mb]
    mb.initialize()
    mb.disconnect()
