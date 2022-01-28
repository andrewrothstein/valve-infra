#!/bin/bash

set -eu

. /usr/local/lib/dashboard/common.sh

[ -z "$@" ] && echo "${red}service name required!${normal}" && exit 1

# $1: service to print status for
show_status() {
	local __service="$1"
	local __status="$(systemctl is-active "$__service")"
	local __color
	case "$__status" in
		"active")
			__color=$green
			;;
		"inactive")
			__color=$red
			;;
		*)
			__color=$yellow
			;;
	esac

	printf "%-18s %s\n" "$__service" "${__color}$__status${normal}"
}

while true; do
	clear

	print_center "Services"

	for s in "$@"; do
		show_status "$s"
	done
	sleep 2
done
