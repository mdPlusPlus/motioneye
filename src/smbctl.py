
# Copyright (c) 2013 Calin Crisan
# This file is part of motionEye.
#
# motionEye is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>. 

import datetime
import logging
import os
import re
import subprocess
import time

import config
import settings

from tornado import ioloop


def find_mount_cifs():
    try:
        return subprocess.check_output('which mount.cifs', shell=True).strip()
    
    except subprocess.CalledProcessError: # not found
        return None


def make_mount_point(server, share, username):
    server = re.sub('[^a-zA-Z0-9]', '_', server).lower()
    share = re.sub('[^a-zA-Z0-9]', '_', share).lower()
    
    if username:
        mount_point = '/media/motioneye_%s_%s_%s' % (server, share, username) 
    
    else:
        mount_point = '/media/motioneye_%s_%s' % (server, share)

    return mount_point


def _is_motioneye_mount(mount_point):
    return bool(re.match('^/media/motioneye_\w+$', mount_point))


def list_mounts():
    logging.debug('listing smb mounts...')
    
    mounts = []
    with open('/proc/mounts', 'r') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 4:
                continue
            
            target = parts[0]
            mount_point = parts[1]
            fstype = parts[2]
            opts = parts[3]
            
            if fstype != 'cifs':
                continue
            
            if not _is_motioneye_mount(mount_point):
                continue
            
            match = re.match('//([^/]+)/(.+)', target)
            if not match:
                continue
            
            if len(match.groups()) != 2:
                continue
            
            server, share = match.groups()
            
            match = re.search('username=(\w+)', opts)
            if match:
                username = match.group(1)
            
            else:
                username = None
                
            logging.debug('found smb mount "//%s/%s" at "%s"' % (server, share, mount_point))
            
            mounts.append({
                'server': server,
                'share': share,
                'username': username,
                'mount_point': mount_point
            })

    return mounts


def mount(server, share, username, password):
    mount_point = make_mount_point(server, share, username)
    logging.debug('mounting "//%s/%s" at "%s"' % (server, share, mount_point))
    
    logging.debug('making sure mount point "%s" exists' % mount_point)
    
    if not os.path.exists(mount_point):    
        os.makedirs(mount_point)
    
    if username:
        opts = 'username=%s,password=%s' % (username, password)
        
    else:
        opts = 'guest'

    try:
        subprocess.check_call('mount.cifs //%s/%s %s -o %s' % (server, share, mount_point, opts), shell=True)
        
    except subprocess.CalledProcessError:
        logging.error('failed to mount smb share "//%s/%s" at "%s"' % (server, share, mount_point))
        
        return False
    
    # test to see if mount point is writable
    try:
        path = os.path.join(mount_point, '.motioneye_' + str(int(time.time())))
        os.mkdir(path)
        os.rmdir(path)
        logging.debug('directory at "%s" is writable' % mount_point)
    
    except:
        logging.error('directory at "%s" is not writable' % mount_point)
        
        return False
    
    return mount_point


def umount(server, share, username):
    mount_point = make_mount_point(server, share, username)
    logging.debug('unmounting "//%s/%s" from "%s"' % (server, share, mount_point))
    
    try:
        subprocess.check_call('umount %s' % mount_point, shell=True)
        
        return True

    except subprocess.CalledProcessError:
        logging.error('failed to unmount smb share "//%s/%s" from "%s"' % (server, share, mount_point))
        
        return False


def update_mounts():
    network_shares = config.get_network_shares()
    
    mounts = list_mounts()
    mounts = dict(((m['server'], m['share'], m['username'] or ''), False) for m in mounts)
    
    for network_share in network_shares:
        key = (network_share['server'], network_share['share'], network_share['username'] or '')
        if key in mounts: # found
            mounts[key] = True
        
        else: # needs to be mounted
            mount(network_share['server'], network_share['share'], network_share['username'], network_share['password'])
    
    # unmount the no longer necessary mounts
    for (network_share['server'], network_share['share'], network_share['username']), required in mounts.items():
        if not required:
            umount(network_share['server'], network_share['share'], network_share['username'])


def umount_all():
    for mount in list_mounts():
        umount(mount['server'], mount['share'], mount['username'])


def _check_mounts():
    logging.debug('checking SMB mounts...')
    
    update_mounts()

    io_loop = ioloop.IOLoop.instance()
    io_loop.add_timeout(datetime.timedelta(seconds=settings.MOUNT_CHECK_INTERVAL), _check_mounts)


if settings.SMB_SHARES:
    # schedule the mount checker
    io_loop = ioloop.IOLoop.instance()
    io_loop.add_timeout(datetime.timedelta(seconds=settings.MOUNT_CHECK_INTERVAL), _check_mounts)