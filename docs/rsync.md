rsync -a \
  --info=progress2,name0,stats2 \
  --outbuf=L \
  --no-inc-recursive \
  --partial-dir=.rsync-partial \
  --mkpath \
  --timeout=30 \
  -e "ssh \
    -o Compression=no \
    -o ServerAliveInterval=5 \
    -o ServerAliveCountMax=3 \
    -o ConnectTimeout=15 \
    -o TCPKeepAlive=yes" \
  /path/to/media/ \
  user@homeserver:/backup/