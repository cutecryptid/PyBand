import sys
sys.path.append('./lib')
from bluepy.btle import *

#mb2 = MiBand2("fc:5a:18:28:15:53")
mb2 = Peripheral("f8:39:cb:d3:7c:33")

for svc in mb2.services:
    print 'SERV: {0}\tUUID: {1}'.format(svc.uuid.getCommonName(), svc.uuid)
    for c in svc.getCharacteristics():
        print '\tCHAR: {0}\t({1}) // HANDLE: {2} // PROPS: {3}'.format(c.uuid.getCommonName(), c.uuid, c.getHandle(), c.propertiesToString())
        for d in c.getDescriptors():
            print '\t\tDESC: {0} // HANDLE: {1}'.format(d.uuid, d.handle)
    print '\n'
