from miband2 import MiBand2
import json

ADDR = "fc:5a:18:28:15:53"

mb2 = MiBand2(ADDR)

svc_export = {}

for svc in mb2.svcs:
    svc_export[str(svc.uuid)] = {"hndStart": svc.hndStart, "hndEnd": svc.hndEnd, "chars":{}}
    for c in svc.getCharacteristics():
        svc_export[str(svc.uuid)]["chars"][str(c.uuid)] = {"handle":c.handle, "valHandle":c.valHandle, "properties":c.properties, "descs":{}}
        for d in c.getDescriptors():
            svc_export[str(svc.uuid)]["chars"][str(c.uuid)]["descs"][str(d.uuid)] = {"handle": d.handle}
    print "SERVICE DONE"

with open('mb2services.json', 'w') as outfile:
    json.dump(svc_export, outfile)
