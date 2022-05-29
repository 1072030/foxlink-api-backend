import pymysql
from app.env import PY_ENV

if PY_ENV == "dev":
    pymysql.install_as_MySQLdb()
