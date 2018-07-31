import sys
sys.path.append('./lib')
from bluepy.btle import *
import time

mac = "f8:39:cb:d3:7c:33"

#mb2 = MiBand2("fc:5a:18:28:15:53")
mb2 = Peripheral(mac, addrType=ADDR_TYPE_RANDOM)


for i in xrange(0, len(mb2.services)):
    svc = mb2.services[i]
    print 'SERV: {0}\tUUID: {1}'.format(svc.uuid.getCommonName(), svc.uuid)
    for j in xrange(0, len(svc.getCharacteristics())):
        c = svc.getCharacteristics()[j]
        print '\tCHAR: {0}\t({1}) // HANDLE: {2} // PROPS: {3}'.format(c.uuid.getCommonName(), c.uuid, c.getHandle(), c.propertiesToString())
        for d in c.getDescriptors():
            print '\t\tDESC: {0} // HANDLE: {1}'.format(d.uuid, d.handle)
    print '\n'
