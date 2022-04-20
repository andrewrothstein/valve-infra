#!/bin/bash

set -eu

. /usr/local/lib/dashboard/common.sh

[ -z "$@" ] && echo "${red}service name required!${normal}" && exit 1

# $1: service to print status for, in the format: name[:expected_status]
# expected_status is optional, defaulting to "active" if not specified.
show_status() {
	local __service="$1"
	local __status="$(systemctl is-active "$__service")"
	local __color
	local __expected="active"

	if echo "$1" | grep -q ":"; then
		__service="$(echo "$1" | cut -d":" -f1)"
		__expected="$(echo "$1" | cut -d":" -f2)"
	fi

	if [ "$__status" = "activating" ]; then
		__color=$yellow
	elif [ "$__status" = "$__expected" ]; then
		__color=$green
	else
		__color=$red
	fi

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
