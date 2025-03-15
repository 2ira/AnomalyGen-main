#!/bin/bash


# 更新软件包列表并安装 MySQL 以及 Python 虚拟环境所需工具
sudo apt-get update
sudo apt-get install -y mysql-server python3-pip python3-venv

# 创建并激活 Python 虚拟环境
python3 -m venv venv
source venv/bin/activate

#设置PYTHONPATH

# 安装 mysql-connector-python
pip install mysql-connector-python

# 运行 MySQL 安全配置脚本（非交互式示例，根据需要调整）
sudo mysql_secure_installation <<EOF

n
y
y
y
y
EOF

# 启动 MySQL 服务
sudo systemctl start mysql



# # 定义数据库、数据表、用户和密码变量
# DB_NAME="callpath"
# TABLE_NAME="method_call"
# USER="new_user"
# PASSWORD="new_password"

# # 删除并重新创建数据库
# sudo mysql -u root <<SQL
# DROP DATABASE IF EXISTS ${DB_NAME};
# CREATE DATABASE ${DB_NAME} CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
# SQL

# # 删除已存在的用户（如果存在），重新创建用户并授予权限
# sudo mysql -u root <<SQL
# DROP USER IF EXISTS '${USER}'@'localhost';
# CREATE USER '${USER}'@'localhost' IDENTIFIED BY '${PASSWORD}';
# GRANT ALL PRIVILEGES ON ${DB_NAME}.* TO '${USER}'@'localhost';
# FLUSH PRIVILEGES;
# SQL

# # 切换到数据库，删除已存在的数据表，并创建新表
# sudo mysql -u root ${DB_NAME} <<SQL
# DROP TABLE IF EXISTS ${TABLE_NAME};
# CREATE TABLE ${TABLE_NAME} (
#     id INT AUTO_INCREMENT PRIMARY KEY,
#     call_seq INT, 
#     enabled INT, 
#     caller TEXT, 
#     callee TEXT, 
#     call_line_no INT, 
#     call_return_type TEXT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci
# ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE utf8mb4_unicode_ci;
# SQL

## 安装其他的依赖
pip install openai==0.28 tiktoken py4j logparser3