ARG BASE_IMAGE=ubuntu:24.04
FROM ${BASE_IMAGE}

ARG DEBIAN_FRONTEND=noninteractive
ARG ROBOCLAW_DOCKER_PROFILE=ubuntu2404
ARG ROBOCLAW_INSTALL_ROS2=0
ARG ROBOCLAW_ROS2_DISTRO=none
ARG ROBOCLAW_ROS2_STAGE1_PYTHON=/usr/local/bin/python3
ARG ROBOCLAW_PYTHON_VERSION=3.11
ENV ROBOCLAW_ROS2_DISTRO=${ROBOCLAW_ROS2_DISTRO}
ENV ROBOCLAW_ROS2_STAGE1_PYTHON=${ROBOCLAW_ROS2_STAGE1_PYTHON}

# Install Python 3.11 on both Ubuntu profiles and Node.js 20 for the WhatsApp bridge.
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
      ca-certificates \
      curl \
      dirmngr \
      git \
      gnupg \
      locales \
      lsb-release \
      software-properties-common && \
    add-apt-repository -y ppa:deadsnakes/ppa && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
      "python${ROBOCLAW_PYTHON_VERSION}" \
      "python${ROBOCLAW_PYTHON_VERSION}-venv" && \
    curl -fsSL https://bootstrap.pypa.io/get-pip.py -o /tmp/get-pip.py && \
    "python${ROBOCLAW_PYTHON_VERSION}" /tmp/get-pip.py && \
    ln -sf "/usr/bin/python${ROBOCLAW_PYTHON_VERSION}" /usr/local/bin/python && \
    ln -sf "/usr/bin/python${ROBOCLAW_PYTHON_VERSION}" /usr/local/bin/python3 && \
    ln -sf /usr/local/bin/pip /usr/local/bin/pip3 && \
    mkdir -p /etc/apt/keyrings && \
    curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg && \
    echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_20.x nodistro main" > /etc/apt/sources.list.d/nodesource.list && \
    apt-get update && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -f /tmp/get-pip.py && \
    rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir --upgrade pip uv

RUN if [ "${ROBOCLAW_INSTALL_ROS2}" = "1" ]; then \
      locale-gen en_US en_US.UTF-8 && \
      update-locale LANG=en_US.UTF-8 LC_ALL=en_US.UTF-8 && \
      curl -fsSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key | gpg --dearmor -o /etc/apt/keyrings/ros-archive-keyring.gpg && \
      . /etc/os-release && \
      echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/ros-archive-keyring.gpg] http://packages.ros.org/ros2/ubuntu ${VERSION_CODENAME} main" > /etc/apt/sources.list.d/ros2.list && \
      apt-get update && \
      apt-get install -y --no-install-recommends \
        "ros-${ROBOCLAW_ROS2_DISTRO}-ros-base" \
        python3-argcomplete \
        python3-colcon-common-extensions && \
      rm -rf /var/lib/apt/lists/*; \
    fi

LABEL roboclaw.docker_profile="${ROBOCLAW_DOCKER_PROFILE}"
LABEL roboclaw.ros2_distro="${ROBOCLAW_ROS2_DISTRO}"

WORKDIR /app

# Install Python dependencies first (cached layer)
COPY pyproject.toml README.md LICENSE ./
RUN mkdir -p roboclaw bridge && touch roboclaw/__init__.py && \
    uv pip install --system --no-cache . && \
    if [ "${ROBOCLAW_INSTALL_ROS2}" = "1" ]; then \
      /usr/bin/python3 -m venv /opt/roboclaw-ros2-venv && \
      /opt/roboclaw-ros2-venv/bin/python -m ensurepip --upgrade && \
      /opt/roboclaw-ros2-venv/bin/python -m pip install --no-cache-dir --upgrade pip && \
      /opt/roboclaw-ros2-venv/bin/python -m pip install --no-cache-dir .; \
    fi && \
    rm -rf roboclaw bridge

# Copy the full source and install
COPY roboclaw/ roboclaw/
COPY bridge/ bridge/
RUN uv pip install --system --no-cache . && \
    if [ "${ROBOCLAW_INSTALL_ROS2}" = "1" ]; then \
      /opt/roboclaw-ros2-venv/bin/python -m pip install --no-cache-dir .; \
    fi

RUN mv /usr/local/bin/roboclaw /usr/local/bin/roboclaw-real
COPY scripts/docker/roboclaw-wrapper.sh /usr/local/bin/roboclaw
RUN chmod +x /usr/local/bin/roboclaw

# Build the WhatsApp bridge
WORKDIR /app/bridge
RUN npm install && npm run build
WORKDIR /app

# Create config directory
RUN mkdir -p /root/.roboclaw

# Gateway default port
EXPOSE 18790

ENTRYPOINT ["roboclaw"]
CMD ["status"]
