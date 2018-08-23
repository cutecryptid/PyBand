# This script extracts the services and characteristics from a MiBand2 and stores
# them on a local file so they can be loaded from a file and save time
# This file is provided in the repo, but you might want to update it

from miband2 import MiBand2
from miband3_lite import MiBand3Lite
import json

#ADDR = "00:11:22:33:44:55"
ADDR = "db:f7:85:30:32:03"

mb = MiBand3Lite(ADDR)

svc_export = {}

for svc in mb.svcs:
    svc_export[str(svc.uuid)] = {"hndStart": svc.hndStart, "hndEnd": svc.hndEnd, "chars":{}}
    for c in svc.getCharacteristics():
        svc_export[str(svc.uuid)]["chars"][str(c.uuid)] = {"handle":c.handle, "valHandle":c.valHandle, "properties":c.properties, "descs":{}}
        for d in c.getDescriptors():
            svc_export[str(svc.uuid)]["chars"][str(c.uuid)]["descs"][str(d.uuid)] = {"handle": d.handle}
    print "SERVICE " + svc.uuid.getCommonName() + " DONE"

with open('mb3services.json', 'w') as outfile:
    json.dump(svc_export, outfile)
