migration:
	alembic upgrade head

generate:
	alembic revision --autogenerate -m "${msg}"