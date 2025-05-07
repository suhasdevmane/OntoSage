This project is under development. Drop a message to access all models from huggingface and all versions of datasets. 




Create a python virtual environment to access different APIs.
```
python -m venv ./abacws-chatbot-venv
```
to activate environment
```
./abacwsenvs/Scripts/activate
c:/_PHD_/Github/abacws-chatbot/abacws-chatbot-venv/Scripts/activate.bat
```

Upgrade pip
```
 python.exe -m pip install --upgrade pip
```

Install dependencies
pip install -r requirements.txt
python -m spacy download en_core_web_sm

# To start this project use docker-compose file and turn ON all services using
```
docker-compose up
```
# To see all services and access GUI oprn index.html in your browser

# Abacws Data Visualiser
Web application made to visualise IoT data for devices in the Abacws building at Cardiff University.\
This repository contains the API and the Visualiser tool, both of which are deployed using [docker](https://www.docker.com/).

Production deployments for these tools can be found at the following locations:
- [API](https://abacws.ggrainger.uk/api/)
- [Visualiser](https://abacws.ggrainger.uk/)

## Docs
You can view the documentation for the two separate services in their respective README files.
- [API](./api/README.md)
- [Visualiser](./visualiser/README.md)

## Docker compose for Abacws Data Visualiser
We recommend using docker compose to deploy this to your own server alongside [traefik](https://traefik.io/traefik/).\
An example compose file can be seen below.

# thingsboard/tb-postgres
ThingsBoard is an open-source IoT platform for data collection, processing, visualization, and device management.

Before starting Docker container run following commands to create a directory for storing data and logs and then change its owner to docker container user, to be able to change user, chown command is used, which requires sudo permissions (command will request password for a sudo access):
```
$ mkdir -p ~/.mytb-data && sudo chown -R 799:799 ~/.mytb-data
$ mkdir -p ~/.mytb-logs && sudo chown -R 799:799 ~/.mytb-logs
```
Execute the following command to run this docker seperately:

$ docker run -it -p 9090:9090 -p 1883:1883 -p 7070:7070 -p 5683-5688:5683-5688/udp -v ~/.mytb-data:/data -v ~/.mytb-logs:/var/log/thingsboard --name mytb --restart always thingsboard/tb-postgres

Where:
```
docker run - run this container
-it - attach a terminal session with current ThingsBoard process output
-p 9090:9090 - connect local port 9090 to exposed internal HTTP port 9090
-p 1883:1883 - connect local port 1883 to exposed internal MQTT port 1883
-p 7070:7070 - connect local port 7070 to exposed internal Edge RPC port 7070
-p 5683-5688:5683-5688/udp - connect local UDP ports 5683-5688 to exposed internal COAP and LwM2M ports
-v ~/.mytb-data:/data - mounts the host's dir ~/.mytb-data to ThingsBoard DataBase data directory
v ~/.mytb-logs:/var/log/thingsboard - mounts the host’s dir ~/.mytb-data to ThingsBoard logs directory
--name mytb - friendly local name of this machine
--restart always - automatically start ThingsBoard in case of system reboot and restart in case of failure.
thingsboard/tb-postgres - docker image
```

After executing this command you can open http://{yor-host-ip}:9090 in your browser. You should see ThingsBoard login page. Use the following default credentials:
```
Systen Administrator: sysadmin@thingsboard.org / sysadmin
Tenant Administrator: tenant@thingsboard.org / tenant
Customer User: customer@thingsboard.org / customer
You can always change passwords for each account in account profile page.

```
## Add your data to the thingsboard devices to talk to the building in natural language and receive data from the database.

All API's and Services are available in following ports:

8090 : Abacws 3D Live visulisation.\
8090/api/ : Abacws 3D backend data API to perform queries.\
8080 : IoT sensor data platform, Thingsboard GUI.\
8080/swagger-ui/ : Thingsboard data query API for all devices and sensors.\
5050 :  PgAdmin GUI to connect thingsboard PostgreSQL database.\
3030 : Apache Jena Fusuki Server to host PDF data and to perform queries.\
5005 :  Rasa Server Host.\
5055 : Rasa Action Server Host.\
8082 : Access Rasa Chatbot WEB UI to talk to the abacws.


to access all API and Services, attach all container with a same network. You can create a network using command 
``` 
docker network create <network_name>
```
For example. I have used network called 'Network abacws-chatbot_my_bridge' in docker-compose file.

To Run All containers run :
```
docker compose up -d 
```
To inspect IP addresses assigned to your containers run: 
```
docker network inspect your_network_name

e.g. docker network inspect abacws-chatbot_my_bridge
```
To extract the container IDs from the JSON output, ru :
```
docker network inspect your_network_name | jq -r '.[0].Containers | keys[]'
docker network inspect abacws-chatbot_my_bridge | jq -r '.[0].Containers | keys[]'

```
For windows,  run :
```
FOR /f "tokens=*" %i IN ('docker ps -q') DO docker inspect -f "{{.Name}} - {{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}" %i
```

To see Containier ID , their anmes and network connected, run :
```
docker ps --format "table {{.ID}}\t{{.Names}}\t{{.Networks}}"

```



REF - https://thingsboard.io/docs/user-guide/install/docker-windows/
Prerequisites
    : DOCKER DESKTOP

Running
Depending on the database used there are three type of ThingsBoard single instance docker images:

thingsboard/tb-postgres - single instance of ThingsBoard with PostgreSQL database.

Recommended option for small servers with at least 1GB of RAM and minimum load (few messages per second). 2-4GB is recommended.

thingsboard/tb-cassandra - single instance of ThingsBoard with Cassandra database.

The most performant and recommended option but requires at least 6GB of RAM. 8GB is recommended.

thingsboard/tb - single instance of ThingsBoard with embedded HSQLDB database.

Note: Not recommended for any evaluation or production usage and is used only for development purposes and automatic tests.


=============================
# Thingsboard Credentials

sysadmin- use default credentials
id- sysadmin@thingsboard.org / pass- sysadmin
id- tenant@thingsboard.org / pass-  tenant
id- customer@thingsboard.org / pass- customer


docker compose up -d            #to up docker compose
docker compose down             # to stop docker-compose 
docker compose logs -f mytb    #to see logs
docker compose stop mytb
docker compose start mytb

docker volumes are saved at \\wsl.localhost\docker-desktop-data\data\docker\volumes\mytb-data\_data\db
windows 11- \\wsl.localhost\docker-desktop-data\data\docker\volumes
reference - https://www.jianshu.com/p/9f2cd43098bb

===========================

# lOGIN TO SHELL
login to the docker container as a root usser to make changes. Use the docker conytainer id to wnter inside the docker.
```
docker exec --user="root" -it b9440731d41b /bin/bash
docker exec --user="root" -it thingsbaord /bin/bash
```
to copy the configuration file from the docker container to the local repository use cp commandfor example 
```
copy conf file
docker cp bf52d15ee378:/etc/thingsboard/conf/thingsboard.yml ./thingsboard/          #replace container id
```
to install required packages to make changes install necessory packages after accessing the container as room user

vim /var/lib/docker/containers/6b88c0c9d4a6a7c290c976265b0357187d69a572402b5889ea7d501fbbcf5da1/hostconfig.json

ref：https://www.jianshu.com/p/9f2cd43098bb

apt-get update
apt-get install vim
apt-get update -y
apt-get install -y iputils-pi
apt-get update && apt-get install -y iputils-ping

```
to see the different files inside the container use command 
```
docker exec -it <CONTAINER ID/NAME>> env        # this wul 

docker exec -it <CONTAINER ID/NAME>> /bin/bash   # opens thingsboard@containerid:/$ psql
```
=============================

# psql command line       

once you enter to the spql command line tool inside the docker container, you use following spql command to explore the postgresql database.
```
List all databases - \l
Switch to another database - \c <db-name>
List database tables - \dt
Describe a table - \d <table-name>
List all schemas - \dn
List users and their roles - \du
Retrieve a specific user - \du <username>
List all functions - \df 
List all views - \dv
Save query results to a file - \o <file-name>
see installed extension  -  \dx 
find available relations  - \d
Quit psql - \q
```
to the the list of available devices inside the thingsboard dtabase use
```
thingsboard=# SELECT * FROM device;             #lists all devices
```


thingsboard itself has postgress installed. the defaults are follows 
- Maintenance database - thingsboard
- default username - thingsboard
- default password- postgres
- hostname - host.docker.internal
you should change the passwords.
      



To change postgress password inside the thingsboard-postgress use 
```postgresdefault
1. docker exec -it <container_name or id of thingsbaord/tb-postgress> bash 
2. psql 
3. show data_directory;
4. \password thingsboard    # to change password for user thingsboard
5. \q to exit psql
```

copy files from the container to the local repository, to change configuration
```
docker cp 82ef4aab77f1:/etc/thingsboard/conf/thingsboard.yml "C:/_PHD_/Github/abacws-chatbot/tb-pg-timescale/" 
```docker cp f5adf293b941:/etc/postgresql/12/main/postgresql.conf "C:/_PHD_/Github/abacws-chatbot/"
Some configurations are need to be changed or should be passed in the docker-compose file.
```
pgadmin
    environment:
      - PGADMIN_DEFAULT_EMAIL=pgadmin@example.com
      - PGADMIN_DEFAULT_PASSWORD=admin
```

<!-- ====================================== adminer and pgadmin ========================= -->


use system- postgreSQL
Server-mytb
Username- thingsboard
password-  postgres
database- thingsboard

result-
id- uuid
cretaed time - bigint
etc



<!-- ========================================= -->



networking for developers only
read https://docs.docker.com/engine/tutorials/networkingcontainers/#:~:text=Docker%20networking%20allows%20you%20to,web%20app%20to%20the%20my_bridge%20.

a] Inspecting the network is an easy way to find out the container's IP address.
```
 docker network inspect bridge
```
b] remove a container from a network 
 ```
 docker network disconnect <network name -default is bridge> <container id or name >
 ```
c] Create your own bridge network
- A bridge network is limited to a single host running Docker Engine. An overlay network can include multiple hosts and is a more advanced topic. 
- For this example, create a bridge network:
 ```
 docker network create -d bridge <network name- e.g. my_bridge>    # -d flag tells Docker to use the bridge driver for the new network
```
d] list the networks
 ```
 docker network ls
 ```
e] Add containers to a network
``` 
docker run -d --net=my_bridge --name db training/postgres
docker run -d --net=my_bridge --name <container name lor id> <image>
```
f] If you inspect your my_bridge you can see it has a container attached. You can also inspect your container to see where it is connected:
 ```
 docker inspect --format='{{json .NetworkSettings.Networks}}'  db
```
g] get ip address of a container
 ```
docker inspect --format='{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' <container name or id>
```


To look your ip address use simple command
```
ipconfig
``` 
and to know your containers ip address use 
``` 
docker inspect <container_name>
```

To adjust the memory usage of docker , in windows add the configuration in the location C:\Users\c21054458\.wslconfig file and restart docker desktop. 
-===================================================================
=================================================================
My output looks as follows: 

C:\_PHD_\Github\abacws-chatbot\thingsboard>docker exec -it timescale psql -U postgres   
psql (14.9)
Type "help" for help.

postgres=# \l
                                  List of databases
    Name     |  Owner   | Encoding |  Collate   |   Ctype    |   Access privileges
-------------+----------+----------+------------+------------+-----------------------
 example     | postgres | UTF8     | en_US.utf8 | en_US.utf8 |
 postgres    | postgres | UTF8     | en_US.utf8 | en_US.utf8 |
 template0   | postgres | UTF8     | en_US.utf8 | en_US.utf8 | =c/postgres          +
             |          |          |            |            | postgres=CTc/postgres
 template1   | postgres | UTF8     | en_US.utf8 | en_US.utf8 | =c/postgres          +
             |          |          |            |            | postgres=CTc/postgres
 thingsboard | postgres | UTF8     | en_US.utf8 | en_US.utf8 |
(5 rows)

postgres=# \c thingsboard 
You are now connected to database "thingsboard" as user "postgres".
thingsboard=# CREATE EXTENSION IF NOT EXISTS timescaledb;
NOTICE:  extension "timescaledb" already exists, skipping
CREATE EXTENSION
thingsboard=# psql -U postgres -h localhost thingsboard
thingsboard-# \dx
                                                List of installed extensions
    Name     | Version |   Schema   |                                      Description
-------------+---------+------------+--------------------------------------------------------------------------------------- 
 plpgsql     | 1.0     | pg_catalog | PL/pgSQL procedural language
 timescaledb | 2.12.0  | public     | Enables scalable inserts and complex queries for time-series data (Community Edition)  
(2 rows)


================================================================


Node_5.01
device token- bW9z8pFxLGQWmmRauup6
curl -v -X POST http://localhost:8080/api/v1/bW9z8pFxLGQWmmRauup6/telemetry --header Content-Type:application/json --data "{temperature:25}"
mosquitto_pub -d -q 1 -h host.docker.internal -p 1883 -t v1/devices/me/telemetry -u bW9z8pFxLGQWmmRauup6 -m "{temperature:25}"
mosquitto_pub -d -q 1 -h 192.168.1.85 -p 1883 -t v1/devices/me/telemetry -u bW9z8pFxLGQWmmRauup6 -m "{temperature:25}"
10.10.212.208

Node_5.02
device token - IUj42BykCyPsRoq17HqY
curl -v -X POST http://localhost:8080/api/v1/IUj42BykCyPsRoq17HqY/telemetry --header Content-Type:application/json --data "{temperature:25}"
mosquitto_pub -d -q 1 -h host.docker.internal -p 1883 -t v1/devices/me/telemetry -u IUj42BykCyPsRoq17HqY -m "{temperature:25}"

Do not forget to add firewall rule to accept the incoming traffic from outside ip to port 1883. in windows add a inbound rule to accept the traffic to port 1883 in firewall settings. follow instruction https://www.youtube.com/watch?v=GBUVyu69Qsk
=======================

# apache-jena-fuski-server 

connect fuseki server to the vs code
1. name- any display name
endpoint- http://localhost:3030/abacws-sensor-network/sparql
usrname- admin
password- Suhas@551993

=======================
# Timescaledb

docker exec -it timescaledb psql -U postgres        # to run psql from docker contaner
\q to exit psql

docker exec -it timescaledb psql --version
timescaledb:
  image: timescale/timescaledb:2.5.0-pg14
  # Rest of your configuration...


Adjust JWT token expiry in thingsboard cnfiguration file.
```
docker exec -it <thingsboard container id>> /bin/bash
```

1. used image
  timescale:
    image: "timescale/timescaledb:latest-pg14"
    container_name: timescale
    environment:
      - POSTGRES_PASSWORD=postgres
      - POSTGRES_USER=postgres
      - POSTGRES_DB=thingsboard
    ports:
      - "5433:5432"
    volumes:
      - timescaledb-data:/var/lib/postgresql/data
    command: ["-c", "shared_preload_libraries=timescaledb"]
    networks:
      - abacws-chatbot_my_bridge

networks:
  abacws-chatbot_my_bridge:
volumes:
  timescaledb-data:



<!-- ========================= installiing timescaleDB ============================= -->

reference- https://docs.timescale.com/self-hosted/latest/install/installation-linux/

1. docker exec --user="root" -it <container id> /bin/bash
2. apt install gnupg postgresql-common apt-transport-https lsb-release wget
3. /usr/share/postgresql-common/pgdg/apt.postgresql.org.sh
4. echo "deb https://packagecloud.io/timescale/timescaledb/debian/ $(lsb_release -c -s) main" | tee /etc/apt/sources.list.d/timescaledb.list 

or
4. echo "deb https://packagecloud.io/timescale/timescaledb/ubuntu/ $(lsb_release -c -s) main" | tee /etc/apt/sources.list.d/timescaledb.list
5. wget --quiet -O - https://packagecloud.io/timescale/timescaledb/gpgkey | apt-key add -
6. apt update

if any issues try
echo "deb http://apt.postgresql.org/pub/repos/apt/ $(lsb_release -cs)-pgdg main" > /etc/apt/sources.list.d/pgdg.list
wget --quiet -O - https://www.postgresql.org/media/keys/ACCC4CF8.asc | apt-key add -




