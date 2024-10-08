# dasFlex server

[Das](https://das2.org) servers typically provide data relevant to space
plasma and magnetospheric physics research.  To retrieve data, an HTTP GET
request is posted to server by a client program.  The server then replies
with data formatted into the requested MIME-type.  The most flexible
reply is a *dasStream* version 3, though other output types are supported,
such as CSV files.

This software, *dasFlex* provides middleware layer between server-side data
readers, which stream data at full resolution to standard out, and remote client
programs such as [SDDAS](http://www.sddas.org/), [SPEDAS](https://github.com/spedas),
and [Autoplot](https://autoplot.org), or custom programs written in Java
([das2java](https://github.com/das-developers/das2java)), 
Python ([das2py](https://github.com/das-developers/das2py)), IDL
([das2pro](https://github.com/das-developers/das2pro), 
[das2dlm](https://github.com/das-developers/das2dlm) ), or C
([das2C](https://github.com/das-developers/das2C) ).  Since dasFlex is a multi-MIME
server, data may also be output as delimited text [CSV](https://github.com/das-developers/das2C/wiki/das3_csv) and as [CDF](https://github.com/das-developers/das2C/wiki/das3_cdf) files, 
which are common in space-physics research.

When a request for data is received, dasFlex inspects the HTTP GET URL against
local data source definitions and solves for the commands needed to
produced the desired output.  The command pipeline is then excuted and output
is transmitted to the client as an HTTP body, or as part of a WebSocket communication
session.

DasFlex itself is released under the GPL, but the core server merely acts 
as a command runner and output transport agent.  Data producing program may be
writen in **any** language, and released under almost **any** license.

## Installation Prequisites

Compilation and installation of a dasFlex server has only been tested in Linux
environments and depends on the following tools:

1. Python >= 3.4
2. Apache2, any remotely recent version
3. [Redis](https://redis.io), known to work with version 3.2 or higher
4. [redis-py](https://redislabs.com/lp/python-redis/), known to work with version 2.10 or higher
5. [lxml](https://github.com/lxml/lxml), known to work with version 4.2 or higher
5. [das2C](https://github.com/das-developers/das2C), latest version recommended
6. [das2py](https://github.com/das-developers/das2py), latest version recommended

Since das2C provides small binaries needed by dasFlex, and since there
are no pre-built das2C packages, installation instructions for both das2C
and dasFlex are included below.  In these instructions the '$' character
is used at the beginning of a line to indicate commands that you'll need to run
in a bourne compatible shell (bash, ksh, etc.).

Example prerequisite package installation commands are provided below for CentOS 7 \.\.\.
```bash
$ sudo yum install gcc git                               
$ sudo yum install expat-devel fftw-devel openssl-devel             
$ sudo yum install python3 python3-numpy python3-devel 
$ sudo pip3 install redis
```
\.\.\. and Debian 9:
```bash
$ sudo apt-get install gcc git                           
$ sudo apt-get install libexpat-dev libfftw3-dev libssl-dev          
$ sudo apt-get install python3-dev python3-distutils python3-numpy
$ sudo apt-get install redis-server                                 
$ sudo apt-get install python3-redis
```

## Get the Source

All sources are now on github.com

```bash
$ git clone https://github.com/das-developers/das2C.git
$ git clone https://github.com/das-developers/das2py.git
$ git clone https://github.com/das-developers/dasFlex.git
```

## Build and Install

Decide where your dasFlex code and configuration information will reside. 
In the example below I've  selected `/var/www/dasflex` but you can choose
any location you like.  These environment variables will be used through out
the setup, so leaving your terminal window open though the testing stage will
save time.

```bash
$ export PREFIX=/var/www/dasflex     # Adjust to taste
$ export N_ARCH=/                    # since das2 servers are typically machine bound
$ export PYVER=3.9                   # minimum 3.6
$ export SERVER_ID=solar_orbiter_2   # for example.  ID should not contain whitespace
```

Test your `PYVER` setting by making sure the following command brings up a
python interpreter:

```bash
$ python$PYVER
```

Build and install commands can run without `sudo` if the install directory
is created manually.  The following will make the install directory and set
it's ownership to the current account.  We will lock it down after install.
```bash
$ sudo mkdir $PREFIX
$ sudo chown $LOGNAME $PREFIX
```

The following sequence will build, test, and install das2C and das2py
if you have all prerequisite libraries installed:

```bash
$ cd das2C
$ make
$ make test     # Contacts remote services, okay if those tests fail
$ make install
$ cd ../

$ cd das2py
$ make 
$ make test     # Also contacts remote servers, okay if those tests fail
$ make install
$ cd ../
```

Now build and install the python module and example configuration files.
Set `--install-lib` and `--prefix` as indicated, unless you want to hand
edit dasflex.conf after installation.  There is no need to run `build`
before this step.

```bash
$ cd ../dasFlex
$ python${PYVER} setup.py install --prefix=${PREFIX} --install-lib=${PREFIX}/lib/python${PYVER}
$ make install
```
You can add the argument `--no-examples` to avoid installing the example
data sources if these are not desired.

Copy over the example configuration file:

```bash
$ cd ${PREFIX}/etc
$ cp dasflex.conf.example dasflex.conf
```

We are done with server software installation, lock down the install area (if desired). 
The `cache` subdirectory shoud be owned by the account that runs asynchronous 
data-reduction processing.  The cache subdirectory should not be owned by the
webserver account, or root, but any other account is fine.
```bash
$ sudo chown -R root:root $PREFIX
$ sudo chown $LOGNAME $PREFIX/cache         # i.e. any non-apache, non-root account
```

## Configure Apache - CGI

Apache configurations vary widely by Linux distribution and personal taste.
The following procedure is provided as an example and has been tested on
CentOS 7.

First determine which directory on your server maps to an Apache HTTPS CGI
directory.  To provide better URLs for your site add the line:

```apache
ScriptAlias /das/ "/var/www/cgi-das/"
```

directly under the line:

```apache
ScriptAlias /cgi-bin/ "/var/www/cgi-bin/"
```

inside the `<IfModule alias_module>` section of httpd.conf.  

Of course the cgi-das directory will have to be created. and on CentOS anyway, the
proper SELinux context applied:
```bash
sudo mkdir /var/www/cgi-das
# You should apply a proper SELinux context to this directory, though the author
# does not know how to do so.  Any contributions on this manner are welcome as
# SELinux does not report to the console and audit logs are ususally empty.
```

Then provide configuration information for your `/var/www/cgi-das` directory
inside the `/etc/httpd/conf.d/ssl.conf` file.  We're editing the *ssl.conf*
instead of httpd.conf because das2 clients may transmit passwords. 


```apache
<Directory "/var/www/cgi-das">
  Options ExecCGI FollowSymLinks

  # Make sure Authorization HTTP header is available to Das CGI scripts
  RewriteRule ^ - [E=HTTP_AUTHORIZATION:%{HTTP:Authorization}]
  RewriteEngine on

  AllowOverride None
  Require all granted
</Directory>
```

By default, authorization headers are not made available to CGI scripts.
The re-write rule above allows the `Authorization` header to be passed down
to the `dasflex_cgimain` script.  This is needed to allow your server to
support password protected data sources.

Now symlink the top level CGI scripts into your new CGI directory.  Choose
the name of the symlink carefully as it will be part of the public URL for
your site:

```bash
$ cd /var/www/cgi-das
$ sudo ln -s $PREFIX/bin/dasflex_cgimain server
$ sudo ln -s $PREFIX/bin/dasflex_cgilog log
```

The main server script needs to be able to find the main log reader
script and vice versa.  If you use something other than the default
values above update the following config entries in your `dasflex.conf`.
```ini
VIEW_LOG_URL = "log"
MAIN_SRV_URL = "server"
```

Set the permissions of the log directory so that Apache can write logging
information:

```bash
$ chmod 0777 $PREFIX/log   # Or change the directory ownership
```

Finally, trigger a re-read of the Apache's configuration data:

```bash
$ sudo systemctl restart httpd.service
$ sudo systemctl status httpd.service
```

## Configure Apache + WebSocket

The dasFlex server includes a websocket daemon for communicating with real-time
data sources.  This is not needed for standard server functionality, but it is
very useful for supporting hardware development, since technicians want to see 
instrument data immediately.  The assumption in the instructions below is that 
Apache will serve as the front door to the included **dasflex_websocd** daemon and
will handle encryption/decription.  The websocket daemon will only listen to the
local host and all backend communication between Apache and dasflex_websocd will
be unencrypted.

First make sure mode the following apache modules are enabled:
```bash
a2enmod proxy proxy_wstunnel proxy_http rewrite
```
For RHEL-like systems, check the conf files in `/etc/httpd/conf.modules.d`.

Second in your applicable SSL server add the following.  If you're using 
the default SSL server on Ubuntu the file is located at `/etc/apache2/sites-enabled/default-ssl.conf`
or for RHEL, `/etc/httpd/conf.d/ssl.conf`.
```
<Location "/dasws/" >
  RewriteEngine on
  RewriteRule ^ - [E=HTTP_AUTHORIZATION:%{HTTP:Authorization}]
  ProxyPreserveHost on
  ProxyPass "ws://localhost:52242/dasws/"
  ProxyPassReverse "ws://localhost:52242/dasws/"
</Location>
```
Here the value ws://localhost:52242/dasws/ should be whatever you've specifed 
for the `WEBSOCKET_URI` in your **dasflex.conf** file.

A client program is included for testing your websocket server.  An example of
running it for the included spectra example would be:
```
python3 dasflex/test/ws_test_client.py \
   wss://localhost/dasws/examples/spectra/flexRT \
   read.time.min=1979-03-01T12:26:11 \
   read.time.max=1979-03-01T12:29:24 \
   format.serial=text
```

The websock server should run as the same user as the regular CGI server.  This
is critical because the log to the same files.  That bears reapeating:

> **NOTE** Run dasflex_websocd as the apache user on your system.

To do this the following command will work work on Debian and derivitives:
```bash
sudo su -s /usr/bin/bash -c "/path/to/dasflex_websocd 127.0.0.1 52242 -D /path/to/log/websock.pid" www-data
```
The user account on Rocky Linux is different, but otherwise the command is the 
same.  A system-d unit file will be created as time permits.

To stop your server send **SIGINT** to the runing daemon
```bash
sudo kill -INT $(cat /path/to/log/websock.pid)
```

## Test the server

Test the server by pointing your web browser at:

```
https://localhost/das/server
https://localhost/das/log
```
If this works, try browsing your new server with Autoplot.  To do so, copy the
following URI into the Autoplot address bar and hit the green "Go" button:

```
vap+das2server:https://localhost/das/server
```

## Next steps

The CGI scripts and worker programs read thier configuration data from the
file:

```bash
$PREFIX/etc/dasflex.conf
```

Take time to customize a few items in your config file such as the 
`site_title` and the `contact_email`.   You may also want change the file
`${PREFIX}/static/logo.png` or even the style sheet at 
`${PREFIX}/static/dasflex.css` to something a little nicer.

**DasFlex** is a caching and web-transport layer for data readers.  Readers
are the programs that generate the initial full resolution data streams.  The
entire purpose of dasFlex and das2 clients is to leverage the output of
your reader programs to produce efficient, interactive science data displays.
Example readers are included in the `$PREFIX/examples` directory to assist you
with the task of creating readers for your own data.  These examples happen to
be written in python, however there is no requirement to use python for your
programs, in fact much more efficent compiled languages such as Java,
[D](https://dlang.org/) and C++ are more suitable for the task.  Any language
may be used so long as:

  1) all data are written to standard output
  2) all error messages are written to standard error

For further information on your dasFlex server instance, including:

  * reader programs
  * authentication 
  * request caching
  * [federated catalog](https://das2.org/browse) integration
  
consult the wiki associated with this repository.

## Examples License

All code in the examples directory (not including the temporary pycdf subdirectory)
is release under the UNLICENSE and may be used without restrictions of any kind.


## Experimental Features

An initial websocket server is included in the package, but dependency handling 
for it is not part of the setup (yet).  To install extra packages, such as trio_websocket
the following custom test commands are handy if you're not using a virtual environment:

```bash
pip install --target=/your/custom/pylib/dir trio_websocket
export PYTHONPATH=/your/custom/pylib/dir
```
Many of the old mission support software sets benefit from this install method.

