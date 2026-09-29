#!/bin/bash
set -e

host="$1"
port="$2"
user="$3"
shift 3
cmd="$@"

until pg_isready -h "$host" -p "$port" -U "$user"; do
  >&2 echo "PostgreSQL недоступен - ожидание..."
  sleep 2
done

>&2 echo "PostgreSQL доступен - выполнение команды"
exec $cmd

