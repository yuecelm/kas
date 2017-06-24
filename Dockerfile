# This image builds Yocto 2.2 jobs using the kas tool

FROM debian:8.8

ENV LOCALE=en_US.UTF-8
RUN apt-get update && \
    apt-get install --no-install-recommends -y locales && \
    sed -i -e "s/# $LOCALE.*/$LOCALE UTF-8/" /etc/locale.gen && \
    dpkg-reconfigure --frontend=noninteractive locales && \
    apt-get install --no-install-recommends -y \
                       gawk wget git-core diffstat unzip file \
                       texinfo gcc-multilib build-essential \
                       chrpath socat cpio python python3 rsync \
                       tar bzip2 curl dosfstools mtools parted \
                       syslinux tree python3-pip bc python3-yaml \
                       lsb-release python3-setuptools && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

RUN wget -nv -O /usr/bin/gosu "https://github.com/tianon/gosu/releases/download/1.10/gosu-amd64" && \
    chmod +x /usr/bin/gosu

COPY . /kas
RUN pip3 install /kas

ENTRYPOINT ["/kas/docker-entrypoint"]
