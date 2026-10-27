# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# This code is based on or derived from Jupyter Notebook
# Copyright (c) 2015 Jupyter Development Team
# Licensed under BSD 3-Clause License
# https://github.com/jupyter/notebook/blob/main/LICENSE

# Configuration file for notebook.

import os
import secrets

c = get_config()  #noqa

# Consume the credential before kernels inherit the server's environment.
# OpenSandbox's bootstrap supplies the same token to execd and this server.
c.IdentityProvider.token = os.environ.pop("JUPYTER_TOKEN", "") or secrets.token_hex(32)
