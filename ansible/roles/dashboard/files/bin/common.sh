#!/bin/bash

set -eu

# colors
red="$(tput setaf 1)"
green="$(tput setaf 2)"
yellow="$(tput setaf 3)"
blue="$(tput setaf 4)"
normal="$(tput sgr0)"

# $1 text to print
print_center() {
	printf "%$(((${#1}+${COLUMNS})/2))s\n" "$1"
}
