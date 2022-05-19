#!/bin/bash

hostname=`cat /proc/sys/kernel/hostname`
cpu_id_max=`cat /sys/devices/system/cpu/possible | cut -d - -f 2`
gpu_id_max=4

function cpufreq() {
    local cpu_id=cpu$1

    local path="/sys/devices/system/cpu/${cpu_id}/cpufreq"

    echo -n "cpufreq,cpu=$cpu_id,host=$hostname "

    # Print the value of all the frequency attributes
    for attr in bios_limit cpuinfo_cur_freq cpuinfo_max_freq cpuinfo_min_freq scaling_cur_freq scaling_max_freq scaling_min_freq; do
        local attr_path="$path/$attr"
        if test -f "$attr_path"; then
            echo -n "$attr=$(<$attr_path)000u,"
        fi
    done

    # Print all the string attributes
    for attr in scaling_driver scaling_governor; do
        local attr_path="$path/$attr"
        if test -f "$attr_path"; then
            echo -n "$attr=\"$(<$attr_path)\","
        fi
    done

    echo "e=1"  # End the list of attributes
}

function amdgpu() {
    local gpu_id=card$1
    local path="/sys/class/drm/$gpu_id/device"

    echo -n "amdgpu,node=$gpu_id,host=$hostname "

    # Print the value of all the attributes that can be quoted verbatim
    for attr in gpu_busy_percent mem_busy_percent mem_info_gtt_total mem_info_gtt_used mem_info_preempt_used mem_info_vis_vram_total mem_info_vis_vram_used mem_info_vram_total mem_info_vram_used current_link_width max_link_width pp_cur_state; do
        local attr_path="$path/$attr"
        if test -f "$attr_path"; then
            echo -n "$attr=$(<$attr_path)u,"
        fi
    done

    # Print the link speed
    for attr in max_link_speed current_link_speed; do
        local attr_path="$path/$attr"
        if test -f "$attr_path"; then
            echo -n "${attr}=$(cat $attr_path | cut -d '.' -f 1)000000u,"
        fi
    done

    # Print all the string attributes
    for attr in power_dpm_force_performance_level power_dpm_state power_state; do
        local attr_path="$path/$attr"
        if test -f "$attr_path"; then
            echo -n "${attr}=\"$(< $attr_path)\","
        fi
    done

    # TODO: Add power collection here: average_cpu_power / average_gfx_power

    # Print the clocks of the different clock domains
    for attr in pp_dpm_mclk pp_dpm_sclk; do
        local attr_path="$path/$attr"
        if test -f "$attr_path"; then
            echo -n "${attr}=$(cat $attr_path | grep '*' | cut -d ' ' -f 2 | egrep -o '[0-9.]+')000000u,"
        fi
    done

    echo "e=1"  # End the list of attributes
}

function dri_node() {
    local vendor_id="$(cat /sys/class/drm/card$1/device/vendor 2> /dev/null)"

    case "$vendor_id" in
    0x1002)
        amdgpu $1
        ;;
    *)
        # Unsupported GPU vendor. Nothing to do
        ;;
    esac

}

# Main loop
while IFS= read -r LINE; do
    # Dump the cpufreq metrics
    for (( i=0; i<=$cpu_id_max; i++ )); do
        cpufreq $i
    done

    # Dump the amdgpu metrics
    for (( i=0; i<=$gpu_id_max; i++ )); do
        dri_node $i
    done
done
