# PyPiMi
Python library to interact with the Xiaomi MiBand 2

# Requirements
This library can only run in LINUX environments since it uses the BluePy library.
You also need a Bluetooth 4.0 capable dongle or similar in order to use the library.

To install the requires libraries run
```
pip install Crypto
pip install bluepy
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

You can include the library from anywhere in your project with a relative import. Sample uses containing all the functionality can be found on the ```mb2api.py``` and ```mb2shell.py``` files. Please note that these scripts won't work out of the box because they are intended to work with our project's local SQL Server Database. And should be modified accordingly and used as reference. There is also ```mb2daemon.py```, that is an attempt to make a an automated synchronization server that works with local files.

The Shell has a parameter to specifiy the storage mode, "db" will try to stablish a connection with the configured relational database, while "json" will work in standalone mode.
