# Ensure XFCE/Garcon always sees the standard application and menu trees.
case ":${XDG_DATA_DIRS:-}:" in
    *:/usr/share:*) ;;
    *) export XDG_DATA_DIRS="/usr/local/share:/usr/share${XDG_DATA_DIRS:+:$XDG_DATA_DIRS}" ;;
esac
case ":${XDG_CONFIG_DIRS:-}:" in
    *:/etc/xdg:*) ;;
    *) export XDG_CONFIG_DIRS="/etc/xdg${XDG_CONFIG_DIRS:+:$XDG_CONFIG_DIRS}" ;;
esac
