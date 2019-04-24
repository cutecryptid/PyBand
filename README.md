# PyBand
Python library to interact with the Xiaomi MiBand 2 and MiBand3

# Requirements
This library can only run in LINUX environments since it uses the BluePy library.
You also need a Bluetooth 4.0 capable dongle or similar in order to use the library.

To install the requires libraries run
```
pip install Crypto
pip install bluepy==1.1.4
```

Optionally, to store the data on a DB, the library used in the MiBand2DB module is pyodbc, you can install it through pip
```
pip install pyodbc
```

To run the shell you need the CMD module
```
pip install pyodbc
```

And finally to run the library through our REST API, you have to install Flask
```
pip install Flask
```

Please note that while the library is easily installed with the previous command, you need a compatible ODBC driver installed in your LINUX environment.

# Usage
All of the scripts have to be ran as superuser since the commands the BluePy library relies on to switch the working mode of your BLE device require those privileges.

You can include the library from anywhere in your project with a relative import. Sample uses containing all the functionality can be found on the ```mb2api.py``` and ```mb2shell.py``` files.

The Shell has a parameter to specifiy the storage mode, "db" will try to stablish a connection with the configured relational database, while "json" will work in standalone mode.

To run the library as an automated server, you have to modify the ```miband_server.service``` file to point ```WorkingDirectory=``` to this project's root folder on your system, and edit ```ExecStart=/path/to/project/root/mb_api.py``` accordingly.

Unlike the Shell script, the API script and Sync Server will only work in DB mode (SQL Server) and not in local JSON mode. This is still a WIP.
