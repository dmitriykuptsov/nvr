#!/usr/bin/python3

# Copyright (C) 2019 strangebit

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

__author__ = "Dmitriy Kuptsov"
__copyright__ = "Copyright 2023, strangebit"
__license__ = "GPL"
__version__ = "0.0.1a"
__maintainer__ = "Dmitriy Kuptsov"
__email__ = "dmitriy.kuptsov@gmail.com"
__status__ = "development"

# Logging
import logging
from logging.handlers import RotatingFileHandler

# import system library
import sys

# Configuration
from config import config

# Threading
import threading

# Errors
import traceback

# Timing
from time import sleep

# Import OS stuff
import os

# Buffer copy functionality
import copy

# Change ownership
import pwd
import grp

# Regular expressions
import re

# Subprocesses
import subprocess

# Datetime stuff
from datetime import datetime

# socket functionality
import socket

import binascii

# Timing
import time

# Checksums
from crccheck.crc import Crc32, Crc32Mpeg2

# Configure logging to console and file
logging.basicConfig(
	level=logging.DEBUG,
	format="%(asctime)s [%(levelname)s] %(message)s",
	handlers=[
		RotatingFileHandler("rtsp_capture.log", backupCount=10),
		logging.StreamHandler(sys.stdout)
	]
);

# Well known PIDs
PAT_PID                    = 0x0;

# Maximum value for the CC
MAX_CC_COUNTER                 = 0x10;

# H264
H264_NAL_NONIDR_SLICE          = 0x1;
H264_NAL_IDR_SLICE             = 0x5;
H264_NAL_SPS                   = 0x7;
H264_NAL_PPS                   = 0x8;

IDR_FRAME_REVERSE_ENGINEERED   = 0x65;
IDR_2_FRAME_REVERSE_ENGINEERED = 0x41;
SPS_FRAME_REVERSE_ENGINEERED   = 0x67;
PPS_FRAME_REVERSE_ENGINEERED   = 0x68;

# Offsets and lengths
TS_PACKET_SIZE             = 0xBC;
CRC32_LENGTH               = 0x4;
TS_HEADER_SIZE             = 0x4;
PMT_OFFSET                 = 0x9;
PROGRAM_INFO_LENGTH_OFFSET = 0xA;
SECTION_LENGTH_OFFSET      = 0x1;
PMT_RECORD_LENGTH          = 0x4;
SECTION_OFFSET             = 0xD;
PAT_PREHEADER_LENGTH       = 0x8;
PMT_PREHEADER_LENGTH       = 0xC;

# Synchronization
SYNC_PACKET_AMOUNT         = 0x5;
UNSYNC_PACKET_AMOUNT       = 0x3;

# Predefined field values
SYNC_BYTE                  = 0x47;

# Adaptation field types
TS_PACKET_PAYLOAD_ONLY           = 0x1;
TS_PACKET_ADAPTATION_ONLY        = 0x2;
TS_PACKET_ADAPTATION_AND_PAYLOAD = 0x3;

# Stream Types
# See http://www.atsc.org/cms/standards/Code-Points-Registry-Rev-35.xlsx
STREAM_TYPE_MPEG1_VIDEO    = 0x01;
STREAM_TYPE_MPEG2_VIDEO    = 0x02;
STREAM_TYPE_MPEG1_AUDIO    = 0x03;
STREAM_TYPE_MPEG2_AUDIO    = 0x04;
STREAM_TYPE_PRIVATE        = 0x06;
STREAM_TYPE_AUDIO_ADTS     = 0x0f;
STREAM_TYPE_H264           = 0x1b;
STREAM_TYPE_MPEG4_VIDEO    = 0x10;
STREAM_TYPE_METADATA       = 0x15;
STREAM_TYPE_AAC            = 0x11;
STREAM_TYPE_MPEG2_VIDEO_2  = 0x80;
STREAM_TYPE_AC3            = 0x81;
STREAM_TYPE_PCM            = 0x83;
STREAM_TYPE_SCTE35         = 0x86;

MAX_BUFFER_SIZE_IN_BYTES   = config["SEQUENCE_LENGTH_IN_BYTES"];

# PES header
PES_HEADER_LENGTH_OFFSET       = 0x8;

def TS_PACKET_SYNC_BYTE(b):
	return (b[0]);
def TS_PACKET_TRANS_ERROR(b):
	return ((b[1]&0x80)>>7);
def TS_PACKET_PAYLOAD_START(b):
	return ((b[1]&0x40)>>6);
def TS_PACKET_PRIORITY(b):
	return ((b[1]&0x20)>>5);
def TS_PACKET_PID(b):
	return (((b[1]&0x1F)<<8) | b[2]);
def TS_PACKET_SCRAMBLING(b):
	return ((b[3]&0xC0)>>6);
def TS_PACKET_ADAPTATION(b):
	return ((b[3]&0x30)>>4);
def TS_PACKET_CONT_COUNT(b):
	return ((b[3]&0x0F)>>0);
def TS_PACKET_ADAPTATION_LENGTH(b):
	return (b[4]);

# This was reverse engineered
# PES header
# https://en.wikipedia.org/wiki/Packetized_elementary_stream
# NAL header
def is_key_frame(b):
	offset = TS_HEADER_SIZE;
	if TS_PACKET_ADAPTATION(b) == TS_PACKET_ADAPTATION_ONLY or TS_PACKET_ADAPTATION(b) == TS_PACKET_ADAPTATION_AND_PAYLOAD:
		adaptation_field_length = b[offset];
		offset += (adaptation_field_length + 1);
	#print "PES header length.... %d" % b[TS_HEADER_SIZE + PES_HEADER_LENGTH_OFFSET];
	#print "Start code.... %d" % (b[offset] << 16 | b[offset + 1] << 8 | b[offset + 2]);
	#print "Stream id.... %d" % (b[offset + 3]);
	offset += PES_HEADER_LENGTH_OFFSET + b[offset + PES_HEADER_LENGTH_OFFSET] + 1;
	# Simply loop through all the bytes, this is rather slow but I did not find other method to search for IDR frame
	# Thanks to the Internet and reverse engineering effort of the existing IPTV streaming service I inderstood how the
	# key frame should look like. 
	sps_found = False;
	pps_found = False;
	idr_found = False;
	#i = offset
	#import sys
	#print "Looking for key frame >>>>>>>>>>>>>>>>>>>>>>>>>>>>"
	#while i < TS_PACKET_SIZE:
	#	sys.stdout.write("%02x" % b[i]);
	#	i += 1;
	#sys.stdout.write("\n");
	while offset + 4 < TS_PACKET_SIZE:
		# Most likely it is possible to avoid the loop if the NALU headers and NALU payload lengths
		# do not change from I-Frame to I-Frame. This can save quite some CPU cycles
		sync_word = ((b[offset] & 0x1F) << 24 | b[offset + 1] << 16 | b[offset + 2] << 8 | b[offset + 3]);
		#sync_word = (b[offset] << 16 | b[offset + 1] << 8 | b[offset + 2]);
		if sync_word == 0x1:
			# The NALU type are the first 5 bits 
			nal_type = (b[offset + 4] & 0x1F);
			#if nal_type == IDR_FRAME_REVERSE_ENGINEERED or nal_type == IDR_2_FRAME_REVERSE_ENGINEERED:
			if nal_type == H264_NAL_IDR_SLICE or nal_type == H264_NAL_NONIDR_SLICE:
				idr_found = True;
			#if nal_type == SPS_FRAME_REVERSE_ENGINEERED:
			if nal_type == H264_NAL_SPS:
				sps_found = True;
			if nal_type == H264_NAL_PPS:
				pps_found = True;
		offset += 1;
	return idr_found and sps_found and pps_found;

class LookupTable():
	def __init__(self, stream_id):
		self.pmt_packets = {};
		self.pat_packets = {};
		self.stream_id_pmt_pid = {};
		self.pmt_pid_stream_id = {};
		self.stream_id_video_pid = {};
		self.stream_id_audio_pid = {};
		self.audio_pid_stream_id = {};
		self.video_pid_stream_id = {};
		self.streams = [];
		self.streams.append(stream_id);
	def get_stream_ids(self):
		return self.streams;
	def is_stream_id_in_list(self, stream_id):
		return stream_id in self.streams;
	def set_pat_packet(self, stream_id, packet):
		self.pat_packets[stream_id] = packet;
	def set_pmt_pid_stream_id(self, stream_id, pmt_pid):
		self.pmt_pid_stream_id[pmt_pid] = stream_id;
		self.stream_id_pmt_pid[stream_id] = pmt_pid;
	def get_stream_id_by_pmt_pid(self, pmt_pid):
		return self.pmt_pid_stream_id.get(pmt_pid);
	def is_valid_pmt_pid(self, pmt_pid):
		logging.debug("Processing PMT pid %d" % pmt_pid);
		stream_id = self.pmt_pid_stream_id.get(pmt_pid, None)
		if stream_id != None:
			return True;
		return False;
	def set_pmt_packet(self, stream_id, packet):
		self.pmt_packets[stream_id] = packet;
	def set_video_pid_stream_id(self, stream_id, video_pid):
		self.stream_id_video_pid[stream_id] = video_pid;
		self.video_pid_stream_id[video_pid] = stream_id;
	def set_audio_pid_stream_id(self, stream_id, audio_pid):
		self.stream_id_audio_pid[stream_id] = audio_pid;
		self.audio_pid_stream_id[audio_pid] = stream_id;
	def get_pat_packet(self, video_pid):
		stream_id = self.video_pid_stream_id[video_pid];
		return self.pat_packets[stream_id];
	def get_pmt_packet(self, video_pid):
		stream_id = self.video_pid_stream_id[video_pid];
		return self.pmt_packets[stream_id];
	def get_stream_id_by_video_pid(self, video_pid):
		return self.video_pid_stream_id.get(video_pid, -1);
	def get_stream_id_by_audio_pid(self, audio_pid):
		return self.audio_pid_stream_id.get(audio_pid, -1);
	def is_valid_video_pid(self, video_pid):
		return self.video_pid_stream_id.get(video_pid, None) != None;
	def is_valid_audio_pid(self, audio_pid):
		return self.audio_pid_stream_id.get(audio_pid, None) != None;

# Sets owner of the folder/file to www-data
def set_ownership(path):
    uid = pwd.getpwnam("www-data").pw_uid;
    gid = grp.getgrnam("www-data").gr_gid;
    os.chown(path, uid, gid);

# Creates the folder and sets the owner of the folder to www-data
def create_folder(path):
    try:
        if not os.path.exists(path):
            os.makedirs(path);
        set_ownership(path)
        return True;
    except Exception as e:
        logging.debug(str(e));
        return False;

# Removes the file from the filesystem
def remove_file(path):
    try:
        os.remove(path);
        return True;
    except:
        return False;

def captureMPEGTS():
    """
    Converts the MP4 files to MPEGTS stream files
    """
    logging.debug("Binding to socket........................")
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((config["MPEGTS_UDP_IP"], config["MPEGTS_UDP_PORT"]))
    #sock.setsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF, 10*1024*1024)
    logging.debug("Setting socket option.................")
    logging.debug("Buffer size --------------------------------------")
    logging.debug(sock.getsockopt(socket.SOL_SOCKET,socket.SO_RCVBUF))
    logging.debug("Buffer size --------------------------------------")

    lookup = LookupTable(config["VALID_CHANNEL"]);
    # Precreate buffer twice the size of the maximum buffer size
    #sequence_buffer = bytearray(MAX_BUFFER_SIZE_IN_BYTES * 2);
    sequence_buffer = {};
    stream_id = config["VALID_CHANNEL"]
    sequence_buffer[stream_id] = bytearray(MAX_BUFFER_SIZE_IN_BYTES * 2);
    base_dir = config["OUTPUT_FOLDER"];
    #program = config["STREAM_ID"];
    #output_folder = "".join([base_dir, "/", str(filling_timestamp)]);
    playing_timestamp = {};
    waiting_timestamp = {};
    filling_timestamp = {};
    buffer_fill = {};
    sequence = {};
    playlist_constructed = {};
    output_folder = {};
    stream_ids = lookup.get_stream_ids();
    playlist_constructed[stream_id] = False;
    playing_timestamp[stream_id] = -1;
    waiting_timestamp[stream_id] = -1;
    filling_timestamp[stream_id] = int(time.time());
    sequence[stream_id] = 1;
    buffer_fill[stream_id] = 0;
    output_folder[stream_id] = config["OUTPUT_FOLDER"];
    if not create_folder(output_folder[stream_id]):
        logging.debug("Could not create folder. Exiting...");
        #exit(-1);
    sync_count = 0;
    lost_packets = 0;
    pmt_pid = 0x0;
    pmt_packet_processed = {};
    video_pid = 0x0;
    audio_pid = 0x0;
    stream_synchronized = False;
    cc_counter = -1;
    pat_commited = False;
    pmt_commited = False;
    end_of_pes = False;
    pat_packet_processed = False;
    #pmt_packet = None;
    #playlist_constructed = False;
    cumulative_buf = bytearray([])
    while True:
        try:
            buf = list([])
            try:
                buf, addr = sock.recvfrom(TS_PACKET_SIZE)
                #sbuf = fd.read(TS_PACKET_SIZE)
                #fd.write(buf)
                #continue
                buf = bytearray(buf)
                logging.debug("Got data on the socket..........")
                #sbuf = bytearray(sbuf)
                #cumulative_buf[len(cumulative_buf):] = sbuf
                #index = 0
                #found = False
                #if not synched:
                #    while index < len(cumulative_buf):
                #        if cumulative_buf[index] == SYNC_BYTE:
                #            if index + TS_PACKET_SIZE > len(cumulative_buf):
                #                break;
                #            logging.debug("SYNC BYTE IS NOT THE FIRST ONE %d " % index)
                #            buf = cumulative_buf[index:index + TS_PACKET_SIZE]
                #            cumulative_buf = cumulative_buf[index + TS_PACKET_SIZE:]
                #            logging.debug("SIZE OF THE BUFFER AFTER %d %d" % (len(cumulative_buf), index))
                #            found = True
                #            break
                #        index += 1
                #if not found:
                #    
                #    continue
            except IOError:
                logging.critical("Socket was closed, cannot continue");
                exit(-1)
            #if len(buf) != TS_PACKET_SIZE:
            #    logging.debug("Invalid packet size %d " % len(buf))
            #    continue;
            if TS_PACKET_SYNC_BYTE(buf) != SYNC_BYTE:
                logging.critical("Invalid synchronization byte: %d %d" % (TS_PACKET_SYNC_BYTE(buf), SYNC_BYTE) )
                continue;
            if TS_PACKET_TRANS_ERROR(buf):
                logging.critical("*******************************TS packet error*******************************")
                # Skip the packet if we have an error
                continue;
            pid = TS_PACKET_PID(buf);
            logging.debug("**************PID of the packet %d *********************" % (pid));
            #Have no idea how and why we have here extra byte but it seems to work that way
            offset = TS_HEADER_SIZE;
            #print "Adaptation header %d" % (TS_PACKET_ADAPTATION(buf));
            #print "PUSI %d" % (TS_PACKET_PAYLOAD_START(buf));
            #Parser is implemented according to the https://github.com/jeoliva/mpegts-basic-parser/blob/master/tsparser.c
            payload_unit_start_indicator = TS_PACKET_PAYLOAD_START(buf);
            if TS_PACKET_ADAPTATION(buf) == TS_PACKET_ADAPTATION_AND_PAYLOAD or TS_PACKET_ADAPTATION(buf) == TS_PACKET_ADAPTATION:
                #print "Adaptation header present and its length is %d" % (TS_PACKET_ADAPTATION_LENGTH(buf));
                offset += (TS_PACKET_ADAPTATION_LENGTH(buf) + 1);
            logging.debug("IS PAT PID? %d" % pid)
            if pid == PAT_PID and not pat_packet_processed:
            #if pid == PAT_PID and not pat_commited:
                pat_packet_processed = True;
                logging.debug("**************** PAT PID ******************");
                # Program association table (PAT)
                # Lets look into the contents and find the PID of the program map table first
                if payload_unit_start_indicator:
                    logging.debug("PUSI bit is set. Skipping %d bytes" % (buf[offset]));
                    offset += ((buf[offset] & 0xFF) + 1);
                table_id = buf[offset];
                logging.debug("Table ID %d" % (table_id));
                section_syntax_indicator = ((buf[offset + 1] & 0x80) >> 7);
                logging.debug("Section syntax indicator %d" % (section_syntax_indicator));
                section_length = (((buf[offset + 1] & 0x0F) << 8) | (buf[offset + 2] & 0xFF));
                logging.debug("SECTION LENGTH: %d" % (section_length));
                transport_stream_id = (((buf[offset + 3] & 0x0F) << 8) | (buf[offset + 4] & 0xFF));
                logging.debug("Transport stream id %d" % (transport_stream_id));
                version_id = (buf[offset + 5] & 0x3e);
                current_next_section_inicator = (buf[offset + 5] & 0x1);
                pmt_pid_found  = False;
                num_programs   = int((section_length - 5 - 4) / 4);
                index = offset + PAT_PREHEADER_LENGTH;
                logging.debug("Number of programs %d " % (num_programs));
                for i in range(num_programs):
                    stream_id = (((buf[index] & 0xFF) << 8) | ((buf[index + 1] & 0xFF)));
                    #pmt_pid = (((buf[index + 2] & 0x1F) << 8) | ((buf[index + 3] & 0xFF)));
                    pmt_pid = (((buf[index + 2] & 0x1F) << 8) | (buf[index + 3] & 0xFF));
                    logging.debug("Program number: %d, PMT PID %d" % (stream_id, pmt_pid));
                    if lookup.is_stream_id_in_list(stream_id):
                        #if not pmt_synced:
                        #pmt_fd = open(config["DEMUX"], "w+");
                        #if pmt_fd < 0:
                        #	print "Opening demux file failed";
                        #	exit(-1);
                        logging.debug("Seting up filter for PMT %d...." % (pmt_pid));
                        #if set_pesfilter(pmt_fd, pmt_pid, DMX_PES_OTHER) < 0:
                        #if add_pidfilter(fd, (pmt_pid & 0xFFFF)):
                        #	logging.debug("Cannot set PMT filter. Exiting...");
                        #	exit(-1);
                        #pmt_pid_found = True;
                        #pmt_synced = True;
                        # Rewriting the PAT
                        section_length = 5 + PMT_RECORD_LENGTH + CRC32_LENGTH;
                        # Header offset, adaptation length field, actual length of the adaptation
                        # Set the payload unit start indicator to 1
                        buf[1] = (buf[1] | 0x40);
                        if TS_PACKET_ADAPTATION(buf) == TS_PACKET_ADAPTATION_AND_PAYLOAD or TS_PACKET_ADAPTATION(buf) == TS_PACKET_ADAPTATION:
                            pointer_length = TS_PACKET_SIZE - CRC32_LENGTH - (TS_PACKET_ADAPTATION_LENGTH(buf) + 1) -  PMT_RECORD_LENGTH - PAT_PREHEADER_LENGTH - 1;
                            offset = TS_HEADER_SIZE + (TS_PACKET_ADAPTATION_LENGTH(buf) + 1);
                        else:
                            pointer_length = TS_PACKET_SIZE - CRC32_LENGTH - PMT_RECORD_LENGTH - PAT_PREHEADER_LENGTH - TS_HEADER_SIZE - 1;
                            offset = TS_HEADER_SIZE;
                        buf[offset] = pointer_length;
                        offset += 1;
                        # Pad with 1's
                        for i in range(0, pointer_length):
                            buf[offset] = 0xFF;
                        offset += pointer_length;
                        offset_table = offset;
                        buf[offset] = table_id;
                        # Section syntax indicator
                        buf[offset + 1] = 0;
                        buf[offset + 1] = (buf[offset + 1] | (section_syntax_indicator << 7));
                        # Section length
                        #print "SECTION LENGTH: %d" % (section_length);
                        buf[offset + 1] = (buf[offset + 1] | ((section_length >> 8) & 0xF));
                        #print buf[offset + 1], ((section_length >> 8) & 0xF);
                        buf[offset + 2] = (section_length & 0xFF);
                        section_length = (((buf[offset + 1] & 0x0F) << 8) | (buf[offset + 2] & 0xFF));
                        #print "SECTION LENGTH: %d" % (section_length);
                        # Transport stream id
                        buf[offset + 3] = ((transport_stream_id >> 8) & 0xFF);
                        buf[offset + 4] = (transport_stream_id & 0xFF);
                        # Version number
                        buf[offset + 5] = 0;
                        buf[offset + 5] = (buf[offset + 5] | ((version_id << 1) & 0x3e));
                        # Current next section indicator
                        buf[offset + 5] = (buf[offset + 5] | (current_next_section_inicator & 0x1));
                        # Set the first section number and last section number to 0x0
                        buf[offset + 6] = 0x0;
                        buf[offset + 7] = 0x0;
                        offset += PAT_PREHEADER_LENGTH;
                        buf[offset] = ((stream_id & 0xFF00) >> 8);
                        buf[offset + 1] = (stream_id & 0xFF);
                        buf[offset + 2] = ((pmt_pid & 0x1F00) >> 8);
                        buf[offset + 3] = (pmt_pid & 0xFF);
                        offset += PMT_RECORD_LENGTH;
                        # Compute the checksum
                        #crc32 = binascii.crc32(buffer(buf[offset_table:offset]));
                        crc32 = Crc32Mpeg2.calc(buf[offset_table:offset]);
                        buf[offset] = ((crc32 & 0xff000000) >> 24);
                        buf[offset + 1] = ((crc32 & 0x00ff0000) >> 16);
                        buf[offset + 2] = ((crc32 & 0x0000ff00) >>  8);
                        buf[offset + 3] = (crc32 & 0x000000ff);
                        pat_packet = copy.deepcopy(buf);
                        logging.debug("----------------------------------- SETTING PMT PID %d ----------------------------------------" % pmt_pid)
                        lookup.set_pat_packet(stream_id, pat_packet);
                        lookup.set_pmt_pid_stream_id(stream_id, pmt_pid);
                        #break;
                    index += PMT_RECORD_LENGTH;
                #if not pmt_pid_found:
                #	print "Program was not found in the PAT table";
                #	continue; # Or should we exit
                continue;
            elif pid == PAT_PID and pat_packet_processed:
                continue;
            # We have found the PMT PID lets look into the internals
            # to find out the PIDs for audio and video elementary streams
            #print pmt_pid == pid, pmt_synced, (not pat_commited)
            #if pid == pmt_pid and pmt_synced and (not pmt_commited):
            #if pid == pmt_pid and pmt_packet_processed:
            logging.debug("Current PID " + str(pid))
            logging.debug("Stream ID " + str(stream_id))
            if lookup.is_valid_pmt_pid(pid) and not pmt_packet_processed.get(pid, False):
                pmt_packet_processed[pid] = True;
                pmt_packet = copy.deepcopy(buf);
                stream_id = lookup.get_stream_id_by_pmt_pid(pid)
                lookup.set_pmt_packet(stream_id, pmt_packet);
                logging.debug("**************** PMT PID ******************");
                if payload_unit_start_indicator:
                    logging.debug("PUSI bit is set. Skipping %d bytes" % (buf[offset]));
                    offset += ((buf[offset] & 0xFF) + 1);
                logging.debug("Offset is %d" % (offset));
                section_syntax_indicator = ((buf[offset + 1] & 0x80) >> 7);
                logging.debug("Section syntax indicator %d" % (section_syntax_indicator));
                logging.debug("PMT Table ID %d" % (buf[offset]));
                program_info_length = (((buf[offset + PROGRAM_INFO_LENGTH_OFFSET] & 0xF) << 8) |
                            (buf[offset + PROGRAM_INFO_LENGTH_OFFSET + 1]));
                logging.debug("PMT program info length %d" % (program_info_length));
                section_length      = (((buf[offset + SECTION_LENGTH_OFFSET] & 0xF) << 8) |
                            (buf[offset + SECTION_LENGTH_OFFSET + 1]));
                logging.debug("PMT section length %d" % (section_length));
                logging.debug("PCR PID: %d" % ((((buf[offset + 8] & 0x1F) << 8) | \
                            (buf[offset + 9]))))
                index               = offset + PMT_PREHEADER_LENGTH + program_info_length;
                counter             = 0;
                num                 = section_length - 9 - program_info_length - 4;
                while counter < num:
                    stream_type    = buf[index + counter] & 0xFF;
                    elementary_pid = (((buf[index + counter + 1] & 0x1F) << 8) | 
                                (buf[index + counter + 2] & 0xFF));
                    es_info_length = (((buf[index + counter + 3] & 0xF) << 8) | 
                                (buf[index + counter + 4]));
                    counter += (5 + es_info_length);
                    # Find the PIDs for audio and video elementary streams
                    # The assumption is such that the H264 codec is being used for video
                    # and MPEG2 audio codec is being used for audio compression
                    logging.debug("Stream type: %d" % (stream_type));
                    logging.debug("Elementary PID: %d" % (elementary_pid)); 
                    if stream_type == STREAM_TYPE_H264:
                        #if not video_pid:
                        video_pid = elementary_pid;
                        lookup.set_video_pid_stream_id(stream_id, video_pid);
                        #video_fd = open(config["DEMUX"], "w+");
                        logging.debug("Seting up filter for video elementary stream %d for stream %d" % (video_pid, stream_id))
                        #if video_fd < 0:
                        #	print "Cannot open file";
                        #	exit(-1);
                        #if set_pesfilter(video_fd, video_pid, DMX_PES_VIDEO) < 0:
                        #if add_pidfilter(fd, video_pid):
                        #	logging.debug("Cannot set video filter. Exiting...");
                        #	exit(-1);
                    if stream_type == STREAM_TYPE_MPEG2_AUDIO or stream_type == STREAM_TYPE_AAC or stream_type == STREAM_TYPE_AC3 or stream_type == STREAM_TYPE_MPEG1_AUDIO:
                        #if not audio_pid:
                        audio_pid = elementary_pid;
                        lookup.set_audio_pid_stream_id(stream_id, audio_pid);
                        logging.debug("Seting up filter for audio elementary stream %d" % audio_pid) 
                        #audio_fd = open(config["DEMUX"], "w+");
                        #if audio_fd < 0:
                        #	print "Cannot open file";
                        #	exit(-1);
                        #if set_pesfilter(audio_fd, audio_pid, DMX_PES_AUDIO) < 0:
                        #if add_pidfilter(fd, audio_pid):
                        #	logging.debug("Cannot set video filter. Exiting...");
                        #	exit(-1);
            elif lookup.is_valid_pmt_pid(pid) and pmt_packet_processed.get(pid, False):
                continue;
            #if pid == PAT_PID:
            #	print "Storing the PAT in the buffer... This should occur only once"
            #	sequence_buffer[buffer_fill:buffer_fill + TS_PACKET_SIZE] = buf;
            #	buffer_fill += TS_PACKET_SIZE;
            #	continue;
            #if pid == pmt_pid:
            #	print "Storing the PMT packet in the buffer... This should occur only once"
            #	sequence_buffer[buffer_fill:buffer_fill + TS_PACKET_SIZE] = buf;
            #	buffer_fill += TS_PACKET_SIZE;
            #	continue;
            # Slice the MPEG-TS stream at I-frame boundary
            #print "PID of the packet %d" % pid;
            #print "Stream ID %d" % (lookup.get_stream_id_by_video_pid(pid));
            #print "lookup.is_valid_video_pid(pid) %d " % lookup.is_valid_video_pid(pid)
            #print "payload_unit_start_indicator %d " % payload_unit_start_indicator
            #if lookup.is_valid_video_pid(pid) and payload_unit_start_indicator == 0x1:
            #	print ">>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>"
            #	print "Is key frame %d" % is_key_frame(buf);
            #	print "<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<"
            logging.debug("Looking up VIDEO PID " + str(pid))
            if lookup.is_valid_video_pid(pid) and payload_unit_start_indicator == 0x1 and is_key_frame(buf):
                stream_id = lookup.get_stream_id_by_video_pid(pid);
                #print "Stream ID %d, Buffer fill level %d, Maximum buffer size %d " % (stream_id, buffer_fill[stream_id], MAX_BUFFER_SIZE_IN_BYTES);
                #print "Stream id %d" % stream_id;
                if buffer_fill[stream_id] >= MAX_BUFFER_SIZE_IN_BYTES:
                    # We need to copy the sequence buffer otherwise some packets can be overwritten
                    sequence_buffer_copy = copy.deepcopy(sequence_buffer[stream_id][0:buffer_fill[stream_id]]);
                    threading.Thread(target=save_buffer, args=(sequence_buffer_copy, output_folder[stream_id], filling_timestamp[stream_id])).start();
                    filling_timestamp[stream_id] = int(time.time());
                    #output_folder[stream_id] = "".join([base_dir, "/", str(stream_id), "/", str(filling_timestamp[stream_id])]);
                    #create_folder(output_folder[stream_id]);
                    # Copy PAT, PMT and first packet of a new PES carrying video data
                    # First two packets of a segment MUST be PAT and PMT packets 
                    # as described in https://tools.ietf.org/html/rfc8216#section-3
                    buffer_fill[stream_id] = 0;
                    sequence_buffer[stream_id][buffer_fill[stream_id]:buffer_fill[stream_id] + TS_PACKET_SIZE] = pat_packet;
                    buffer_fill[stream_id] += TS_PACKET_SIZE;
                    sequence_buffer[stream_id][buffer_fill[stream_id]:buffer_fill[stream_id] + TS_PACKET_SIZE] = pmt_packet;
                    buffer_fill[stream_id] += TS_PACKET_SIZE;
                    continue;
                #if (sequence[stream_id] == MAX_SEQUENCE_PER_FOLDER / 2) and buffer_fill[stream_id] >= (MAX_BUFFER_SIZE_IN_BYTES * 0.1) and not playlist_constructed[stream_id] and playing_timestamp[stream_id] > 0:
                #	playlist_constructed[stream_id] = True;
                #	logging.debug("Constructing playlist (timestamp %d)" % (playing_timestamp[stream_id]));
                #	threading.Thread(target=construct_playlist, args=("".join([base_dir, "/", str(stream_id), "/", str(playing_timestamp[stream_id])]), "".join([base_dir, "/", str(stream_id), "/"]), WEB_PATH, stream_id, playing_timestamp[stream_id], config["ENABLE_STREAM_ENCRYPTION"], )).start();
                sequence_buffer[stream_id][buffer_fill[stream_id]:buffer_fill[stream_id] + TS_PACKET_SIZE] = buf;
                buffer_fill[stream_id] += TS_PACKET_SIZE;
                continue;
                #elif pid == video_pid and pid != 0x0:
            elif lookup.is_valid_video_pid(pid):
                stream_id = lookup.get_stream_id_by_video_pid(pid);
                logging.debug("Stream id %d, buffer fill %d" % (stream_id, buffer_fill[stream_id]));
                sequence_buffer[stream_id][buffer_fill[stream_id]:buffer_fill[stream_id] + TS_PACKET_SIZE] = buf;
                buffer_fill[stream_id] += TS_PACKET_SIZE;
                continue;
            if lookup.is_valid_audio_pid(pid):
                stream_id = lookup.get_stream_id_by_audio_pid(pid);
                #if pid == audio_pid and pid != 0x0:
                logging.debug("AUDIO Stream id %d, buffer fill %d" % (stream_id, buffer_fill[stream_id]));
                sequence_buffer[stream_id][buffer_fill[stream_id]:buffer_fill[stream_id] + TS_PACKET_SIZE] = buf;
                buffer_fill[stream_id] += TS_PACKET_SIZE;
        except Exception as e:
            logging.critical("Exception occured while converting the file")
            logging.critical(e);
            traceback.print_exc()
        #sleep(1)

# Saves the buffer into the output folder
def save_buffer(buf, output_folder, timestamp):
	#print "Saving the buffer of size %d" % (len(buf));
	try:
		# Obtain the lock
		#fd = open("".join([output_folder, "/", "lock"]), "w+");
		#fd.write("processing...");
		#fd.flush();
		#fd.close();
		fd = open("".join([output_folder, "/", str(timestamp), ".raw"]), "wb");
		logging.debug("Saving the buffer...")
		fd.write(buf);
		fd.flush();
		fd.close();
		#I think there is no need to do extra conversion since we already have MPEG2-TS stream which should be readable by the players
		#The conversion is needed if we need to use different container type for example MPEG-4 contaiener.
		#Also Flash does not support MPEG2 audio, so we need to transcode audio signal to AAC for example
		logging.debug("SAVGING BUFFER TO OUTPUT: TIMESTAMP: %d" % timestamp)
		ts_path_no_extension = "".join([output_folder, "/", str(timestamp)]);
		result=os.popen("".join([config["EXEC_DIR"], "/", config["CONVERT_RAW_TS"], " ", ts_path_no_extension, " ", output_folder])).read().strip();
		#os.remove("".join([output_folder, "/", "sequence", str(timestamp), ".raw"]));
		set_ownership("".join([ts_path_no_extension, ".ts"]));
		# Release the lock
		#remove_file("".join([output_folder, "/", "lock"]));
		#set_ownership("".join([output_folder, "/", "sequence", str(timestamp), ".ts"]));
	except Exception as e:
		logging.debug("Error saving the buffer...")
		logging.debug(str(e));
		exit(-1);

def capturing(config):
    """
    Captures the stream, slices it and writes to the disk
    """
    while True:
        folder = config["OUTPUT_FOLDER"]
        if not os.path.exists(config["OUTPUT_FOLDER"]):
            os.makedirs(folder)
        try:
            subprocess.run(["ffmpeg", \
                    "-i", \
                    config["RTSP_URL"], \
                    #"-rtsp_transport", \
                    #config["TRANSPORT_PROTOCOL"], \
                    "-vcodec", "copy", \
                    "-acodec", "copy", \
                    "-preset", "veryfast",\
                    "-mpegts_flags", "pat_pmt_at_frames", \
                    "-copyts", \
                    "-f", "mpegts", \
                    "udp://" + str(config["MPEGTS_UDP_IP"]) + ":" + str(config["MPEGTS_UDP_PORT"]) + "?pkt_size=188&buffer_size=65535", \
                    #"out.ts"
                    ])
        except Exception as e:
            logging.critical("Exception occured while capturing the video stream ....!!!!")
            logging.critical(e);
            traceback.print_exc()
        logging.debug("Capturing process died, restarting the ffmpeg process")
        sleep(10)

def cleanup(config):
    """
    Cleans up old MP4 files
    """
    while True:
        try:
            if os.path.exists(config["OUTPUT_FOLDER"]):
                files = os.listdir(config["OUTPUT_FOLDER"])
                now = int(datetime.now().timestamp())
                for file in files:
                    if re.match("[0-9]+\.(mp4|mpeg4|mkv|ts)", file):
                        ts = int(file.split(".")[0])
                        if ts <= now - int(config["MAX_VIDEO_LIFETIME"]):
                            logging.debug("Removing the file")
                            os.remove(file)
        except Exception as e:
            logging.critical("Exception occured while removing the file... !!!")
            logging.critical(e);
        sleep(config["CLEAN_UP_INTERVAL"])

capture_loop = threading.Thread(target = capturing, args = (config, ), daemon = True);
capture_loop.start()

cleanup_loop = threading.Thread(target = cleanup, args = (config, ), daemon = True);
cleanup_loop.start()

capture_ts_loop = threading.Thread(target = captureMPEGTS, args = (), daemon = True);
capture_ts_loop.start();

main_loop = True;

while main_loop:
    logging.debug("Running RTSP stream capturing application");
    sleep(10)
