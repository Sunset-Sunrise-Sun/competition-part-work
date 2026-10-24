"""Opt-in GitHub issue queue and draft-PR publisher.

All writes are scoped to the configured repository and the task's dedicated
`autopilot/*` branch. There is deliberately no merge or default-branch push
operation. Enable only after a least-privilege token and base branch are set.
"""
from __future__ import annotations

import base64
import json
import os
import re
import subprocess
import time
from collections import deque
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from ..interfaces import TaskSource
from ..models import ReviewResult, ReviewVerdict, RunResult if False else TaskSpec
