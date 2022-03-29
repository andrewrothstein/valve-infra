#!/bin/bash

set -eu

. /usr/local/lib/dashboard/common.sh

# $1: service to print status for
show_nic() {
	local __nic="$1"
	local __sysfs="/sys/class/net/$__nic"

	if [ ! -d "$__sysfs" ]; then
		printf "%-8s %s\n" "$__nic" "${red}does not exist!${normal}"
		return
	fi

	local __status=$(<$__sysfs/operstate)
	local __color
	local __ip="$(ip a show $__nic | grep -e 'inet\s' |tr -s ' ' | cut -d' ' -f3)"
	case "$__status" in
		"unknown")
			__status="???"
			__color=$yellow
			;;
		"up")
			__color=$green
			;;
		*)
			__color=$red
			;;
	esac
	printf "%-8s %s%-4s %s%s\n" "$__nic" "${__color}" "$__status" "$__ip" "${normal}"
}

while true; do
	clear

	print_center "Networking"

	for n in "$@"; do
		show_nic "$n"
	done
	sleep 2
done

#[ -z "$1" ] && echo "service name required!" && exit 1

