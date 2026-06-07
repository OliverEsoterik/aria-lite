#!/bin/bash
# start_services.sh - Starts Minikube and maintains the TimescaleDB port-forward

echo ">>> Starting Minikube..."
minikube start

echo ">>> Waiting for timescaledb service to be available..."
until kubectl get service timescaledb > /dev/null 2>&1; do
  echo "...waiting for service..."
  sleep 5
done

while true; do
  echo ">>> Starting port-forward (5432:5432)..."
  kubectl port-forward service/timescaledb 5432:5432
  
  echo ">>> Port-forward crashed or stopped. Restarting in 5 seconds..."
  sleep 5
done
