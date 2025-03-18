#!/bin/bash

sudo apt-get update
sudo apt-get install -y mysql-server python3-pip python3-venv

python3 -m venv venv
source venv/bin/activate

pip install mysql-connector-python
sudo mysql_secure_installation <<EOF

n
y
y
y
y
EOF

sudo systemctl start mysql


DB_NAME="callpath"
TABLE_NAME="method_call"
USER="new_user"
PASSWORD="new_password"

sudo mysql -u root <<SQL
DROP DATABASE IF EXISTS ${DB_NAME};
CREATE DATABASE ${DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
SQL


sudo mysql -u root <<SQL
DROP USER IF EXISTS '${USER}'@'localhost';
CREATE USER '${USER}'@'localhost' IDENTIFIED BY '${PASSWORD}';
GRANT ALL PRIVILEGES ON ${DB_NAME}.* TO '${USER}'@'localhost';
FLUSH PRIVILEGES;
SQL


sudo mysql -u root ${DB_NAME} <<SQL
DROP TABLE IF EXISTS ${TABLE_NAME};
CREATE TABLE ${TABLE_NAME} (
    id INT AUTO_INCREMENT PRIMARY KEY,
    call_seq INT, 
    enabled INT, 
    caller TEXT, 
    callee TEXT, 
    call_line_no INT, 
    call_return_type TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE utf8mb4_unicode_ci;
SQL

pip install openai==0.28 tiktoken py4j logparser3