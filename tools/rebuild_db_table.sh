rm -f app/alembic/versions/*
alembic upgrade head
alembic revision --autogenerate -m "init"
alembic upgrade head
