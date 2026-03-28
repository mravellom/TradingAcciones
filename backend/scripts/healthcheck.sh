#!/bin/bash
curl -sf http://localhost:8000/api/v1/system/health || exit 1
