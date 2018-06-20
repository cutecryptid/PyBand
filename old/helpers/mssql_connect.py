import pyodbc
import unicodedata

# Some other example server values are
# server = 'localhost\sqlexpress' # for a named instance
# server = 'myserver,port' # to specify an alternate port
server = '10.0.2.2'
database = 'clepitodb'
username = 'clepito'
password = 'Itly26.'

cnxn = pyodbc.connect('DRIVER={ODBC Driver 17 for SQL Server};Server='+server+';Database='+database+';uid='+username+';pwd='+ password)
cursor = cnxn.cursor()

cursor.execute("""SELECT d.mac, lastDate = max(m.fechaInicial)
                FROM Dispositivo d
                JOIN Medidas m
                ON d.dispositivoId = m.dispositivoId
                GROUP BY d.mac""")

devices_last_sync = {}
while True:
    row = cursor.fetchone()
    if not row:
        break
    devices_last_sync[row.mac] = row.lastDate

print devices_last_sync
