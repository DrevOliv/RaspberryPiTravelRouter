import json
import os

from fastapi import APIRouter

from TravelRouter.helpers.api_response import ApiResponse
from TravelRouter.helpers.run_command import run_in_thread

router = APIRouter()


