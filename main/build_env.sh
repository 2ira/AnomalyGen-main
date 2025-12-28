#!/bin/bash

# refresh package lists and install dependencies
sudo apt-get update -y
sudo apt-get install -y \
    python3-pip \
    python3-venv \
    python3-distutils \
    mariadb-server \
    mariadb-client \
    maven

sudo apt-get install -y make build-essential libssl-dev zlib1g-dev \
libbz2-dev libreadline-dev libsqlite3-dev wget curl llvm \
libncurses5-dev libncursesw5-dev xz-utils tk-dev libffi-dev liblzma-dev git

# install pyenv for managing Python versions
git clone https://github.com/pyenv/pyenv.git ~/.pyenv

echo 'export PYENV_ROOT="$HOME/.pyenv"' >> ~/.bashrc
echo 'export PATH="$PYENV_ROOT/bin:$PATH"' >> ~/.bashrc
echo 'eval "$(pyenv init -)"' >> ~/.bashrc

source ~/.bashrc

pyenv install 3.10.12

pyenv local 3.10.12

# build Python virtual environment
python -m venv venv
source venv/bin/activate

# install build tools for Python packages
sudo apt-get update && sudo apt-get install -y python3-dev gcc g++

# install sql-connector for Python
pip install mysql-connector-python

# config MariaDB（MySQL）
sudo mysql_secure_installation <<EOF

n
y
y
y
y
EOF

# start and enable MariaDB service
sudo systemctl start mysql
sudo systemctl enable mysql

DB_NAME="callpath"
TABLE_NAME="method_call"
USER="new_user"
PASSWORD="new_password"

sudo mysql -u root <<SQL
DROP DATABASE IF EXISTS ${DB_NAME};
CREATE DATABASE ${DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
DROP USER IF EXISTS '${USER}'@'localhost';
CREATE USER '${USER}'@'localhost' IDENTIFIED BY '${PASSWORD}';
GRANT ALL PRIVILEGES ON ${DB_NAME}.* TO '${USER}'@'localhost';
FLUSH PRIVILEGES;
CREATE TABLE ${DB_NAME}.${TABLE_NAME} (
    id INT AUTO_INCREMENT PRIMARY KEY,
    call_seq INT, 
    enabled INT, 
    caller TEXT, 
    callee TEXT, 
    call_line_no INT, 
    call_return_type TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE utf8mb4_unicode_ci;
SQL


pip install openai tiktoken py4j logparser3

# if tiktoken is not installed, install it:pip install tiktoken -i https://pypi.org/simple --no-cache-dir