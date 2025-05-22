#!/bin/bash

# Function to check if a command exists
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Function to display help
show_help() {
    echo "Usage: ./dev.sh [command]"
    echo ""
    echo "Commands:"
    echo "  up        Start all services"
    echo "  down      Stop all services"
    echo "  build     Rebuild all services"
    echo "  logs      Show logs from all services"
    echo "  shell     Open a shell in the backend container"
    echo "  test      Run backend tests"
    echo "  migrate   Run database migrations"
    echo "  init-db   Initialize database with test data"
    echo "  help      Show this help message"
}

# Check if docker is installed
if ! command_exists docker; then
    echo "Error: docker is not installed"
    exit 1
fi

# Check if docker-compose is installed
if ! command_exists docker-compose; then
    echo "Error: docker-compose is not installed"
    exit 1
fi

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "Creating .env file from .env.example..."
    cp backend/.env.example .env
fi

# Process commands
case "$1" in
    up)
        docker-compose up -d
        ;;
    down)
        docker-compose down
        ;;
    build)
        docker-compose build
        ;;
    logs)
        docker-compose logs -f
        ;;
    shell)
        docker-compose exec backend bash
        ;;
    test)
        docker-compose exec backend pytest
        ;;
    migrate)
        docker-compose exec backend python manage.py migrate
        ;;
    init-db)
        docker-compose exec backend python manage.py create_test_data
        ;;
    help)
        show_help
        ;;
    *)
        show_help
        exit 1
        ;;
esac 