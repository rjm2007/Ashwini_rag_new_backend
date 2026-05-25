#!/usr/bin/env bash
set -euo pipefail

# This script builds images, pushes to ECR, and updates ECS services.
echo "Build and push images using your CI or local docker commands."
echo "Then register updated task definitions and update ECS services."
