FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /bot
COPY bot.py combat.py world.py mechfight.py ./
USER 65534:65534
ENTRYPOINT ["python3", "-u", "/bot/bot.py"]
