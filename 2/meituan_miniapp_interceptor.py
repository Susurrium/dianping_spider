# -*- coding:utf-8 -*-
"""mitmdump addon entrypoint for Meituan WeChat mini-program captures.

This keeps Meituan captures isolated under mitm_logs/meituan/ while reusing the
existing mini-program API parsing logic.
"""

import os

os.environ.setdefault("DP_CAPTURE_NAMESPACE", "meituan")
os.environ.setdefault("DP_CAPTURE_APPIDS", "wxde8ac0a21135c07d")

from dianping_interceptor import *  # noqa: F401,F403
