from threading import Thread
import time
import random
from Queue import Queue

def task(idx):
    print "Task number %s, working!" % idx
    slept = random.randint(5,10)
    time.sleep(slept)
    print "Task %s after %s seconds" % (idx, slept)

def worker():
    while True:
        item = q.get()
        task(item)
        q.task_done()

q = Queue()
for i in range(5):
     t = Thread(target=worker)
     t.daemon = True
     t.start()

for item in range(1,10):
    q.put(item)

q.join()
