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
	local __ip
	case "$__status" in
		"up")
			__color=$green
			local __ip="$(ip a show $__nic | grep -e 'inet\s' |tr -s ' ' | cut -d' ' -f3)"
			__status="$__status ($__ip)"
			;;
		*)
			__color=$red
			;;
	esac
	printf "%-8s %s\n" "$__nic" "${__color}$__status${normal}"
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

