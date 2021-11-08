#!/bin/bash

# colors
red="$(tput setaf 1)"
green="$(tput setaf 2)"
yellow="$(tput setaf 3)"
normal="$(tput sgr0)"

# $1: service to print status for
show_status() {
	local __service="$1"
	__status="$(systemctl is-active "$__service")"
	local __color
	case __status in
		active)
			__color=$green
			;;
		inactive)
			__color=$red
			;;
		*)
			__color=$yellow
			;;
	esac

	printf "%-9s %-32s %-8s %-16s\n" "Service:" "$__service" "Status:" "${color}$__status${normal}"
}

deps=()
for s in $(systemctl list-dependencies infra.target --plain); do
	[[ "$s" == *".service" ]] || continue
	deps+=("$s")
done


while true; do
	clear
	for d in "${deps[@]}"; do
		show_status "$d"
	done
	sleep 2
done
