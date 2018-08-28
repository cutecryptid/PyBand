import datetime
import pyodbc

# Module to connect to a SQL Server DB and interact with it from the MBServer (Shell/API)
# MySQL implementation is pending and should be done on another file
# Most of the methods will be very similar, but take care

def get_device_last_sync(cnxn_string, address):
    connection = pyodbc.connect(cnxn_string, timeout=3)
    cursor = connection.cursor()
    cursor.execute("""SELECT d.mac, lastDate = max(m.fechaInicial)
                    FROM Dispositivo d
                    JOIN Medidas m
                    ON d.dispositivoId = m.dispositivoId
                    WHERE d.mac = ?
                    GROUP BY d.mac""", str(address.upper()))
    row = cursor.fetchone()
    connection.close()
    if row:
        return row.lastDate
    else:
        return None

def is_device_registered(cnxn_string, address):
    connection = pyodbc.connect(cnxn_string, timeout=3)
    cursor = connection.cursor()
    cursor.execute("""SELECT d.registrado FROM Dispositivo d
                    WHERE d.mac = ?""", str(address.upper()))
    row = cursor.fetchone()
    connection.close()
    if row:
        return row.registrado
    else:
        return 0

def get_device_id(cnxn_string, address):
    connection = pyodbc.connect(cnxn_string, timeout=3)
    cursor = connection.cursor()
    cursor.execute("""SELECT d.dispositivoId FROM Dispositivo d
                    WHERE d.mac = ?""", str(address.upper()))
    row = cursor.fetchone()
    connection.close()
    if row:
        return row.dispositivoId
    else:
        return -1

def get_device_by_id(cnxn_string, id):
    connection = pyodbc.connect(cnxn_string, timeout=3)
    cursor = connection.cursor()
    cursor.execute("""SELECT * FROM Dispositivo
                    WHERE dispositivoId = ?""", id)
    row = cursor.fetchone()
    connection.close()
    return row

def get_device_user(cnxn_string, dev_id):
    connection = pyodbc.connect(cnxn_string, timeout=3)
    cursor = connection.cursor()
    cursor.execute("""SELECT d.dispositivoId, u.* FROM Dispositivo d
                    JOIN DispositivoUsuario du
                    ON du.dispositivoId = d.dispositivoId
                    JOIN Usuario u
                    ON du.usuarioId = u.usuarioId
                    WHERE d.dispositivoId = ?
                    AND du.fechaBaja IS NULL""", dev_id)
    row = cursor.fetchone()
    connection.close()
    return row


def get_device_alarms(cnxn_string, address):
    connection = pyodbc.connect(cnxn_string, timeout=3)
    cursor = connection.cursor()
    cursor.execute("""SELECT a.indiceAlarma, a.hora, a.minuto, a.activada, a.repeticion
                    FROM Alarmas a JOIN Dispositivo d ON a.dispositivoId = d.dispositivoId
                    WHERE d.mac = ?
                    ORDER BY a.indiceAlarma""", str(address.upper()))

    device_alarms = []
    while True:
        row = cursor.fetchone()
        if not row:
            break
        device_alarms += [{"hour": row.hora, "minute": row.minuto,
                            "enabled": row.activada, "repetition": row.repeticion}]
    connection.close()
    return device_alarms

def get_device_alarms_by_id(cnxn_string, dev_id):
    connection = pyodbc.connect(cnxn_string, timeout=3)
    cursor = connection.cursor()
    cursor.execute("""SELECT *
                    FROM Alarmas WHERE dispositivoId = ?
                    ORDER BY indiceAlarma""", dev_id)

    device_alarms = []
    while True:
        row = cursor.fetchone()
        if not row:
            break
        device_alarms += [row]
    connection.close()
    return device_alarms


def register_device(cnxn_string, address, type):
    connection = pyodbc.connect(cnxn_string, timeout=3)
    cursor = connection.cursor()
    cursor.execute("""SELECT d.registrado, d.dispositivoId FROM Dispositivo d
                    WHERE d.mac = ?""", str(address.upper()))

    row = cursor.fetchone()
    if row:
        cursor.execute("UPDATE Dispositivo SET registrado = 1 WHERE mac = ?", str(address.upper()))
    else:
        cursor.execute("""INSERT INTO Dispositivo(nombre, mac, tipoDispositivo, registrado)
                          VALUES (?, ?, ?, ?)""",
                          'MiBand2', str(address.upper()), type, 1)
    connection.commit()
    connection.close()
    if row:
        return row.dispositivoId
    else:
        return -1

def unregister_device(cnxn_string, dev_id):
    connection = pyodbc.connect(cnxn_string, timeout=3)
    cursor = connection.cursor()
    cursor.execute("UPDATE Dispositivo SET registrado = 0 WHERE dispositivoId = ?", dev_id)
    connection.commit()
    connection.close()

def update_battery(cnxn_string, address, battery):
    connection = pyodbc.connect(cnxn_string, timeout=3)
    cursor = connection.cursor()
    cursor.execute("UPDATE Dispositivo SET bateria = ? WHERE mac = ?", battery, str(address.upper()))
    connection.commit()
    connection.close()

def write_activity_data(cnxn_string, device):
    connection = pyodbc.connect(cnxn_string, timeout=3)
    cursor = connection.cursor()
    activity_data = device.getActivityDataBuffer()
    address = device.addr

    print("Storing {0} activity data frames".format(len(activity_data)))

    dev_id = get_device_id(cnxn_string, address)
    if dev_id >= 0:
        for frame in device.activityDataBuffer:
            cursor.execute("""INSERT INTO Medidas(fechaInicial, dispositivoId, categoria, pasos, intensidad, pulsaciones, unidades)
                              VALUES (?, ?, ?, ?, ?, ?, ?)""",
                              frame.dtm.toDatetime(), dev_id, frame.type, frame.steps, frame.intensity, frame.heartrate, 'pasos')
        connection.commit()
    connection.close()

def get_activity_data(cnxn_string, dev_id, start_date, end_date):
    connection = pyodbc.connect(cnxn_string, timeout=3)
    cursor = connection.cursor()
    cursor.execute("""SELECT m.fechaInicial, m.categoria, m.pasos, m.intensidad,
                    m.pulsaciones, du.usuarioId
                    FROM Medidas m JOIN DispositivoUsuario du
                    ON m.dispositivoId = du.dispositivoId
					AND m.fechaInicial >= du.fechaAlta
					AND m.fechaInicial <= ISNULL(du.fechaBaja, SYSDATETIME())
                    WHERE m.dispositivoId = ?
                    AND fechaInicial >= ?
                    AND fechaInicial <= ?
                    ORDER BY fechaInicial""",
                    dev_id, start_date, end_date)
    rows = cursor.fetchall()
    connection.close()
    return rows

def delete_alarm(cnxn_string, dev_id, alarm_id):
    connection = pyodbc.connect(cnxn_string, timeout=3)
    cursor = connection.cursor()
    cursor.execute("""SELECT *
                      FROM Alarmas
                      WHERE dispositivoId = ?
                      ORDER BY indiceAlarma""", dev_id)

    tmp_aid = alarm_id
    rows = cursor.fetchall()[tmp_aid+1:]
    for r in rows:
        # Set each alarm to the values of the next one
        cursor.execute("""UPDATE Alarmas
                          SET hora = ?, minuto = ?, activada = ?, repeticion = ?
                          WHERE indiceAlarma = ? AND dispositivoId = ?""",
                          r.hora, r.minuto, r.activada, r.repeticion, tmp_aid, dev_id)
        tmp_aid += 1
    # ... and delete the last one
    cursor.execute("""DELETE FROM Alarmas
                      WHERE indiceAlarma = ? AND dispositivoId = ?""",
                      tmp_aid, dev_id)
    connection.commit()
    connection.close()

def delete_all_alarms(cnxn_string, dev_id):
    connection = pyodbc.connect(cnxn_string, timeout=3)
    cursor = connection.cursor()
    cursor.execute("DELETE FROM Alarmas where dispositivoId = ?", dev_id)
    connection.commit()
    connection.close()

def set_alarm(cnxn_string, dev_id, alarm, alarm_id):
    connection = pyodbc.connect(cnxn_string, timeout=3)
    cursor = connection.cursor()
    cursor.execute("""SELECT *
                      FROM Alarmas
                      WHERE dispositivoId = ?
                      AND indiceAlarma = ?""", dev_id, alarm_id)
    row = cursor.fetchone()
    if row:
        # Alarm ID exists, update
        cursor.execute("""UPDATE Alarmas
                           SET hora = ?, minuto = ?, activada = ?, repeticion = ?
                           WHERE indiceAlarma = ? AND dispositivoId = ?""",
                           alarm.hour, alarm.minute, alarm.enabled, alarm.repetitionMask, alarm_id, dev_id)
    else:
        # Alarm ID doesn't exist, create
        cursor.execute("""INSERT INTO Alarmas(dispositivoId, indiceAlarma, hora, minuto, activada, repeticion)
                        VALUES (?, ?, ?, ?, ?, ?)""",
                        dev_id, alarm_id, alarm.hour, alarm.minute, alarm.enabled, alarm.repetitionMask)
    connection.commit()
    cursor.execute("""SELECT *
                      FROM Alarmas
                      WHERE dispositivoId = ?
                      AND indiceAlarma = ?""", dev_id, alarm_id)
    row = cursor.fetchone()
    connection.close()
    return row


def get_alias(name, surname, dni):
    alias = name
    for ap in surname.split():
        alias += ap[:2].upper()
    alias += dni[-2:]
    return alias

def get_user_data(cnxn_string, user_id):
    connection = pyodbc.connect(cnxn_string, timeout=3)
    cursor = connection.cursor()
    cursor.execute("""SELECT * FROM Usuario
                    WHERE usuarioId = ?""", user_id)
    row = cursor.fetchone()
    user = None
    if row:
        bd = row.fecha_nacimiento
        user = {"alias": get_alias(row.nombre, row.apellidos, row.dni),
                "height": row.altura, "weight": row.peso, "birth": (bd.year, bd.month, bd.day),
                "sex": row.sexo, "id":row.usuarioId}
    connection.close()
    return user

def get_aspuser_by_email(cnxn_string, user_email):
    connection = pyodbc.connect(cnxn_string, timeout=3)
    cursor = connection.cursor()
    cursor.execute("""SELECT * FROM AspNetUsers
                    WHERE Email = ?""", user_email)
    row = cursor.fetchone()
    connection.close()
    return row

def compare_password(cnxn_string, user_id, pwd_hash):
    connection = pyodbc.connect(cnxn_string, timeout=3)
    cursor = connection.cursor()
    cursor.execute("""SELECT * FROM AspNetUsers
                    WHERE Id = ?
                    AND PasswordHash = ?""",
                    user_id, pwd_hash)
    row = cursor.fetchone()
    connection.close()
    if row:
        return True
    else:
        return False

def set_device_user(cnxn_string, dev_id, user_id, position):
    connection = pyodbc.connect(cnxn_string, timeout=3)
    cursor = connection.cursor()
    cursor.execute("""SELECT fechaBaja FROM DispositivoUsuario
                      WHERE dispositivoId = ?
                      AND fechaBaja IS NULL""",
                      dev_id)
    down_date = cursor.fetchone()

    if not down_date and (dev_id >= 0):
        cursor.execute("""INSERT INTO DispositivoUsuario(usuarioId, dispositivoId, fechaAlta, ubicacion)
                          VALUES (?, ?, ?, ?)""",
                          user_id, dev_id, datetime.datetime.now(), position)
        connection.commit()
        connection.close()
        return True
    else:
        print ("MiBand2 still belongs to some user, release it first")
        connection.close()
        return False

def release_device_user(cnxn_string, dev_id):
    connection = pyodbc.connect(cnxn_string, timeout=3)
    cursor = connection.cursor()
    cursor.execute("""UPDATE DispositivoUsuario
                      SET fechaBaja = ?
                      WHERE dispositivoId = ?
                      AND fechaBaja IS NULL""",
                      datetime.datetime.now(), dev_id)

    if cursor.rowcount == 1:
        connection.commit()
        connection.close()
        return True
    else:
        connection.close()
        return False
