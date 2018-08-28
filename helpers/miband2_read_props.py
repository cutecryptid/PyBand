import sys
import binascii
sys.path.append('./lib')
from miband2 import MiBand2

# Script to list the GATT Services of a MB2 and read them if they're readable (modify to use MB3)

mb2 = MiBand2("fc:5a:18:28:15:53")

for svc in mb2.services:
    print 'SERV: {0}\tUUID: {1}'.format(svc.uuid.getCommonName(), svc.uuid)
    for c in svc.getCharacteristics():
        if c.supportsRead():
            print '\tCHAR: {0}\t({1}) // HANDLE: {2} // VALUE: {3}'.format(c.uuid.getCommonName(), c.uuid, c.getHandle(), binascii.hexlify(c.read()))
        else:
            print '\tCHAR: {0}\t({1}) // HANDLE: {2} // PROPS: {3}'.format(c.uuid.getCommonName(), c.uuid, c.getHandle(), c.propertiesToString())
    print '\n'
