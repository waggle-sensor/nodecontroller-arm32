#!/usr/bin/env python3
# ANL:waggle-license
#  This file is part of the Waggle Platform.  Please see the file
#  LICENSE.waggle.txt for the legal details of the copyright and software
#  license.  For more details on the Waggle project, visit:
#           http://www.wa8.gl
# ANL:waggle-license
'''
This module contains methods relating to the construction and interpretation
of waggle packets. The main functions to examine in this class are pack and
unpack. This module handles all CRC checking for the packets, so any
sucessfully unpacked packet is known to be correct.

TODO Sean: I'll clean this up at some point, but am isolating it for now. I'm
currently using it to provide a simple interface to the Beehive messaging
server. I'll also have it depend less directly on the explicit file structure
of a Waggle node so it can be used for testing...
'''
from crcmod.predefined import mkCrcFun
from struct import pack
import io as StringIO
import time
import logging
import struct

logging.basicConfig()
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)



#Where each piece of information in a packet header is stored, by byte
# Total header size is 40 bytes.
HEADER_LOCATIONS = {
    "prot_ver"         : 0,
    "flags"            : 1,
    "len_body"         : 2,
    "time"             : 4,
    "msg_mj_type"      : 8,
    "msg_mi_type"      : 9,
    "snd_session"      : 10,    # For Friday: just zero. Eventually automatic
    "s_uniqid"         : 12,    # Find from /etc/waggle/hostname
    "ext_header"       : 20,    # Just 0
    "resp_session"     : 22,    # Normally 0, sometimes used
    "r_uniqid"         : 24,    # Defined as 0 for the cloud
    "snd_seq"          : 32,    # Tracked by this module
    "resp_seq"         : 35,    # Normally 0, sometimes used
    "crc-16"           : 38
}
#The length of each piece of data, in bytes
HEADER_BYTELENGTHS = {
    "prot_ver"         : 1,
    "flags"            : 1,
    "len_body"         : 2,
    "time"             : 4,
    "msg_mj_type"      : 1,
    "msg_mi_type"      : 1,
    "snd_session"      : 2,
    "s_uniqid"         : 8,
    "ext_header"       : 2,
    "resp_session"     : 2,
    "r_uniqid"         : 8,
    "snd_seq"          : 3,
    "resp_seq"         : 3,
    "crc-16"           : 2
}

SIZE_2_TYPE =  [ 'c' for i in range(16)]
# '>' means big-endian
SIZE_2_TYPE[1] = '>B' # unsigned char
SIZE_2_TYPE[2] = '>H' # unsigned short
SIZE_2_TYPE[4] = '>I' # unsigned int
SIZE_2_TYPE[8] = '>q' # long long

#The total header length
HEADER_LENGTH = 40
FOOTER_LENGTH = 4
MAX_SEQ_NUMBER = pow(2,8*HEADER_BYTELENGTHS["snd_seq"])
MAX_PACKET_SIZE = 1024

VERSION = "0.3"

# Sequence becomes zero when the node starts again or when the package is
# reimported
SEQUENCE = 0

#The /etc/waggle folder has waggle specific information
S_UNIQUEID_HEX=None


#Create the CRC functions
crc32fun = mkCrcFun('crc-32')
crc16fun = mkCrcFun('crc-16')

crc16_position = HEADER_LOCATIONS['crc-16']


def _pack_int(value, size):
    return struct.pack(SIZE_2_TYPE[size], value)


def nodeid_int2hexstr(node_id):
    #return hex(node_id)[2:].zfill(2*HEADER_BYTELENGTHS["s_uniqid"])
    return "%0s"%format(node_id,'x').lower().zfill(2*HEADER_BYTELENGTHS["s_uniqid"])

def pack(header_data, message_data=""):
    """
        Takes header and message information and yields packets representing that data.

        :param dictionary header_data: A dictionary containing the header data
        :param string/FileObject message_data: The data to be packed into a Packet
        :yields: string
        :raises KeyError: A KeyError will be raised if the header_data dictionary is not properly formatted
    """
    global SEQUENCE
    # global S_UNIQUEID_HEX_INT
    global VERSION

    #Generate the automatic fields
    auto_header = {
        "prot_ver"         : VERSION,
        "flags"            : (1, 1, True),
        "len_body"         : len(message_data),
        "time"             : int(time.time()),
        "snd_session"      : 0,
        "s_uniqid"         : 0,  # S_UNIQUEID_HEX_INT,
        "ext_header"       : 0,
        "resp_session"     : 0,
        "r_uniqid"         : 0,
        "snd_seq"          : SEQUENCE,
        "resp_seq"         : 0,
    }
    #and update them with user-supplied values
    auto_header.update(header_data)


    #If it's a string, make it a file object
    if(type(message_data) is str):
        message_data = StringIO.StringIO(message_data)

    #If it's under 1K, send it off as a single packet
    #Jump to the end of the file
    message_data.seek(0,2)

    header = None

    #See if it is less than 1K
    if(message_data.tell() < MAX_PACKET_SIZE):
        try:
            header = pack_header(auto_header)
        except KeyError as e:
            raise

        #Save the short message to a string
        message_data.seek(0)
        msg = message_data.read()
        message_data.close()

        #Calculate the CRC, pack it all up, and return the result.
        SEQUENCE = (SEQUENCE + 1) % MAX_SEQ_NUMBER
        msg_crc32 = bin_pack(crc32fun(msg),FOOTER_LENGTH)

        yield header + msg + msg_crc32

    #Multi-packet
    else:
        length = message_data.tell()
        message_data.seek(0)
        packetNum = 0

        # Create smaller packets MAX_PACKET_SIZE bytes at a time, also attach packet number
        while length > MAX_PACKET_SIZE:
            try:
                header = pack_header(auto_header)
            except KeyError as e:
                raise
            msg = bin_pack(packetNum,4) + message_data.read(MAX_PACKET_SIZE)
            SEQUENCE = (SEQUENCE + 1) % MAX_SEQ_NUMBER
            packetNum += 1
            msg_crc32 = bin_pack(crc32fun(msg),FOOTER_LENGTH)
            yield header + msg + msg_crc32
            length -= MAX_PACKET_SIZE

        # Finish sending the message
        if length > 0:
            header = pack_header(auto_header)
            msg = bin_pack(packetNum,4) + message_data.read(MAX_PACKET_SIZE)
            SEQUENCE = (SEQUENCE + 1) % MAX_SEQ_NUMBER
            msg_crc32 = bin_pack(crc32fun(msg),FOOTER_LENGTH)
            yield header + msg + msg_crc32

def unpack(packet):
    """
        Turns a packet object into a tuple containing the header data and message body

        :param string packet: The packet data to be unpacked
        :rtype: tuple(dictionary, string)
        :raises IOError: An IOError will be raised if a CRC fails in the packet
        :raises KeyError: An IndexError will be raised if a packet header is the wrong length
    """
    #crc32fun = mkCrcFun('crc-32')
    header = None
    if(crc32fun(packet[HEADER_LENGTH:-FOOTER_LENGTH]) != _bin_unpack(packet[-FOOTER_LENGTH:])):
        raise IOError("Packet body CRC-32 failed.")
    try:
        header = _unpack_header(packet[:HEADER_LENGTH])
    except Exception as e:
        logger.error("_unpack_header failed: "+str(e))
        raise

    return (header, packet[HEADER_LENGTH:-FOOTER_LENGTH])



#def print_packet(packet):
#    (header, body) = unpack(packet)
#
#    for key,value in header.items():
#        logger.debug("%s: %d", (key, value))
#
#    logger.debug("body: %s\n" %(body))
#



def pack_header(header_data):
    """
        Attempt to pack the data from the header_data dictionary into binary format according to Waggle protocol.

        :param dictionary header_data: The header data to be serialized
        :rtype: string
        :raises KeyError: An exception will be raised if the provided dictionary does not contain required information
    """

    header = str()
    try:
        header += _pack_version(header_data["prot_ver"])                                                   # Serialize protocol version
        header += _pack_flags(header_data["flags"])                                                        # Packet flags
        header += bin_pack(header_data["len_body"],HEADER_BYTELENGTHS["len_body"])          # Length of message body
        header += bin_pack(header_data["time"],HEADER_BYTELENGTHS["time"])                  # Timestamp
        header += bin_pack(header_data["msg_mj_type"], HEADER_BYTELENGTHS["msg_mj_type"])   # Message Major Type
        header += bin_pack(header_data["msg_mi_type"], HEADER_BYTELENGTHS["msg_mi_type"])   # Message Minor Type
        header += bin_pack(header_data["ext_header"], HEADER_BYTELENGTHS["ext_header"])     # Optional extended header
        header += bin_pack(header_data["s_uniqid"],HEADER_BYTELENGTHS["s_uniqid"])          # Sender unique ID
        header += bin_pack(header_data["r_uniqid"],HEADER_BYTELENGTHS["r_uniqid"])          # Recipient unique ID
        header += bin_pack(header_data["snd_session"],HEADER_BYTELENGTHS["snd_session"])    # Send session number
        header += bin_pack(header_data["resp_session"],HEADER_BYTELENGTHS["resp_session"])  # Response session number
        header += bin_pack(header_data["snd_seq"],HEADER_BYTELENGTHS["snd_seq"])            # Send sequence number
        header += bin_pack(header_data["resp_seq"],HEADER_BYTELENGTHS["resp_seq"])          # Response sequence number
    except KeyError as e:
        raise KeyError("Header packing failed. The required dictionary entry %s was missing!" % str(e))


    #Compute the header CRC and stick it on the end
    #crc16 = mkCrcFun('crc-16')
    header += bin_pack(crc16fun(header),HEADER_BYTELENGTHS['crc-16'])

    return header


def get_header(packet):
    """
        Given a complete packet, this method will return the header as a dictionary.

        :param string packet: A complete packet.
        :rtype: dictionary
        :raises IndexError: An IndexError will be raised if the packed header is not 40 bytes long
        :raises IOError: An IOError will be raised if the packet header fails its CRC-16 check
    """
    try:
        header = _unpack_header(packet[:HEADER_LENGTH])
        return header
    except Exception as e:
        raise


"""
    (bytearray header) Sets header field in an bytearray. Value also has to be an bytearray.
"""
def set_header_field(header_bytearray, field, value):
    try:
        field_position = HEADER_LOCATIONS[field]
        field_length = HEADER_BYTELENGTHS[field]
    except Exception as e:
        logger.error("Field name unknown: %s" % (str(e)) )
        raise

    if len(value) != field_length:
        e = ValueError("data length: %d bytes, but field is of size: %d bytes (field: %s)" % (len(value), field_length, field) )
        logger.error(str(e))
        raise e

    if (len(header_bytearray) != HEADER_LENGTH):
        e = ValueError("header length is not correct: %d vs HEADER_LENGTH=%d" %(len(header_bytearray), HEADER_LENGTH) )
        logger.error(str(e))
        raise e

    for i in range(field_length):
        header_bytearray[field_position+i] = value[i]



"""
    (bytearray header) Calculates the header crc and accordingly sets the crc-16 field.
"""
def write_header_crc(header_bytearray):

    new_crc = crc16fun(str(header_bytearray[:crc16_position]))

    new_crc_packed = bin_pack(new_crc,HEADER_BYTELENGTHS['crc-16'])

    set_header_field(header_bytearray, 'crc-16', new_crc_packed)



def bin_pack(n, size):
    """
        Takes in an int n and returns it in binary string format of a specified length

        :param int n: The integer to be converted to binary
        :param int size: The number of bytes that the integer will be represented with
        :rtype: string
    """
    packed = bytearray(size)

    for i in range(1, size + 1):
        packed[-i] = 0xff & (n >> (i - 1)*8)

    return str(packed)





"""
-------------------------------------------------------------------------------------------------------------------
                                          private methods start here
-------------------------------------------------------------------------------------------------------------------
"""


def _unpack_header(packed_header):
    """
        Given a packed header, this method will return a dictionary with the unpacked contents.

        :param string packed_header: A string representing a waggle header
        :rtype: Dictionary
        :raises IndexError: An IndexError will be raised if the packed header is not 40 bytes long
        :raises IOError: An IOError will be raised if the packet header fails its CRC-16 check
    """

    # Check header length
    if len(packed_header) != HEADER_LENGTH:
        raise IndexError("Tried to unpack a waggle header that was %d instead of %d bytes long." % (len(packed_header), HEADER_LENGTH ) )

    header_IO = StringIO.StringIO(packed_header)

    #Check the CRC
    #CRC16 = mkCrcFun('CRC-16')
    header_IO.seek(HEADER_LOCATIONS["crc-16"])
    headerCRC = header_IO.read(2)
    if(crc16fun(packed_header[:-2]) != _bin_unpack(headerCRC)):
        raise IOError("Header CRC-16 check failed")
    header_IO.seek(0)

    # The header passed the CRC check. Hooray! Now return a dictionary containing the info.
    header = {
        "prot_ver"     : _unpack_version(header_IO.read(HEADER_BYTELENGTHS["prot_ver"])),        # Load protocol version
        "flags"        : _unpack_flags(header_IO.read(HEADER_BYTELENGTHS["flags"])),             # Load flags
        "len_body"     : _bin_unpack(header_IO.read(HEADER_BYTELENGTHS["len_body"])),            # Load message body length
        "time"         : _bin_unpack(header_IO.read(HEADER_BYTELENGTHS["time"])),                # Load time
        "msg_mj_type"  : _bin_unpack(header_IO.read(HEADER_BYTELENGTHS["msg_mj_type"])),         # Load message major type
        "msg_mi_type"  : _bin_unpack(header_IO.read(HEADER_BYTELENGTHS["msg_mi_type"])),         # Load message minor type
        "ext_header"   : _bin_unpack(header_IO.read(HEADER_BYTELENGTHS["ext_header"])),          # Load extended header
        "s_uniqid"     : _bin_unpack(header_IO.read(HEADER_BYTELENGTHS["s_uniqid"])),            # Load sender unique ID
        "r_uniqid"     : _bin_unpack(header_IO.read(HEADER_BYTELENGTHS["r_uniqid"])),            # Load recipient unique ID
        "snd_session"  : _bin_unpack(header_IO.read(HEADER_BYTELENGTHS["snd_session"])),         # Load send session number
        "resp_session" : _bin_unpack(header_IO.read(HEADER_BYTELENGTHS["resp_session"])),        # Load recipient session number
        "snd_seq"      : _bin_unpack(header_IO.read(HEADER_BYTELENGTHS["snd_seq"])),             # Load send sequence number
        "resp_seq"     : _bin_unpack(header_IO.read(HEADER_BYTELENGTHS["resp_seq"]))             # Load recieve sequence number
    }

    header_IO.close()
    return header

def _pack_flags(flags):
    """
        For internal use.
        Takes a tuple representing the message priorities and FIFO/LIFO preference and packs them to one byte.

        :param tuple(int,int,bool) flags:
        :rtype: string
    """
    return chr((flags[0] << 5) | (flags[1] << 2) | (flags[2] << 1))


def _unpack_flags(flagByte):
    """
        For internal use.
        Takes in the priority byte from the header and returns a tuple containing the correct information.

        :param string flagByte: The priority byte from the header
        :rtype: Tuple(Int, Int, Bool)
    """
    return ((ord(flagByte) & 0xe0) >> 5, (ord(flagByte) & 0x1c) >> 2, bool((ord(flagByte) & 0x02) >> 1))


def _unpack_version(version):
    """
        For internal use.
        Returns the protocol in string form.

        :param string version: byte representing the version
        :rtype: string
    """
    v = ord(version)
    major = v & 0xf0
    minor = v & 0x0f

    # return the version in human-readable form. For example: "0x03" becomes "0.3".
    return str(major) + "." + str(minor)

def _pack_version(version):
    """
        For internal use.
        Returns the protocol as a binary

        :param string version: The version in human-readable format, i.e. "0.3"
        :rtype: The protocol version as a 1 byte string
    """
    versions = version.split(".")
    major = int(versions[0])
    minor = int(versions[1])

    return chr((major << 4) | (0xf & minor))




def _bin_unpack(string):
    """
        For internal use.
        Takes in a string and returns it in integer format

        :param string string: The binary string to read
        :rtype: int
    """
    x = 0

    for i in range(1, len(string) + 1):
        x = x | (ord(string[-i]) << (i - 1)*8)

    return x
