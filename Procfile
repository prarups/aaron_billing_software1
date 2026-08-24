web: bash -c "python manage.py migrate --noinput && gunicorn -k uvicorn.workers.UvicornWorker config.asgi:application --bind 0.0.0.0:$PORT"
