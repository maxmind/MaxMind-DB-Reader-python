#include <Python.h>
#include <arpa/inet.h>
#include <maxminddb.h>
#include <netinet/in.h>
#include <structmember.h>
#include <sys/socket.h>

#define __STDC_FORMAT_MACROS
#include <inttypes.h>

#ifdef __GNUC__
#define UNUSED(x) UNUSED_##x __attribute__((__unused__))
#else
#define UNUSED(x) UNUSED_##x
#endif

typedef struct {
    PyObject *ReaderType;
    PyObject *MetadataType;
    PyObject *MaxMindDB_error;
} _maxminddb_state;

static inline _maxminddb_state*
get_maxminddb_state(PyObject *module)
{
    _maxminddb_state *state = PyModule_GetState(module);
    assert(state != NULL);
    return (_maxminddb_state *)state;
}

static struct PyModuleDef maxminddb_module;

#define _maxminddbstate_type(_t) \
    (get_maxminddb_state(PyType_GetModuleByDef(_t, &maxminddb_module)))

typedef struct {
    PyObject_HEAD
    MMDB_s *mmdb;
    PyObject *closed;
} ReaderObject;

typedef struct {
    PyObject_HEAD
    PyObject *binary_format_major_version;
    PyObject *binary_format_minor_version;
    PyObject *build_epoch;
    PyObject *database_type;
    PyObject *description;
    PyObject *ip_version;
    PyObject *languages;
    PyObject *node_count;
    PyObject *record_size;
} MetadataObject;

static int get_record(ReaderObject *self, PyObject *args, PyObject **record);
static bool format_sockaddr(struct sockaddr *addr, char *dst);
static PyObject *from_entry_data_list(ReaderObject *self, MMDB_entry_data_list_s **entry_data_list);
static PyObject *from_map(ReaderObject *self, MMDB_entry_data_list_s **entry_data_list);
static PyObject *from_array(ReaderObject *self, MMDB_entry_data_list_s **entry_data_list);
static PyObject *from_uint128(ReaderObject *self, const MMDB_entry_data_list_s *entry_data_list);
static int ip_converter(PyObject *obj, struct sockaddr_storage *ip_address);

static int
ReaderType_init(ReaderObject *self, PyObject *args, PyObject *kwargs)
{
    static char *arg_names[] = {"database", "mode", NULL};
    PyObject *filepath = NULL;
    int mode = 0;

    _maxminddb_state *state = _maxminddbstate_type(Py_TYPE(self));
    assert(state != NULL);

    if (!PyArg_ParseTupleAndKeywords(args, kwargs,
                                     "O&|i", arg_names,
                                     PyUnicode_FSConverter,
                                     &filepath,
                                     &mode)) {
        return -1;
    }

    char *filename = PyBytes_AS_STRING(filepath);
    if (filename == NULL) {
        return -1;
    }

    if ((mode != 0) && (mode != 1)) {
        Py_XDECREF(filepath);
        PyErr_Format(
            PyExc_ValueError,
            "Unsupported open mode (%i). Only "
            "MODE_AUTO and MODE_MMAP_EXT are supported by this extension.",
            mode);
        return -1;
    }

    if (access(filename, R_OK) < 0) {
        PyErr_SetFromErrnoWithFilenameObject(PyExc_OSError, filepath);
        Py_XDECREF(filepath);
        return -1;
    }

    MMDB_s *mmdb = (MMDB_s *)malloc(sizeof(MMDB_s));
    if (mmdb == NULL) {
        Py_XDECREF(filepath);
        PyErr_NoMemory();
        return -1;
    }

    ReaderObject *mmdb_obj = (ReaderObject *)self;
    if (mmdb_obj == NULL) {
        Py_XDECREF(filepath);
        free(mmdb);
        PyErr_NoMemory();
        return -1;
    }

    uint16_t status = MMDB_open(filename, MMDB_MODE_MMAP, mmdb);
    Py_XDECREF(filepath);

    if (status != MMDB_SUCCESS) {
        free(mmdb);
        PyErr_Format(state->MaxMindDB_error,
                     "Error opening database file (%s). Is this a valid "
                     "MaxMind DB file?",
                     filename);
        return -1;
    }

    mmdb_obj->mmdb = mmdb;
    mmdb_obj->closed = Py_False;

    return 0;
}

static PyObject *
Reader_get(ReaderObject *self, PyObject *args, PyObject *UNUSED(kwargs))
{
    PyObject *record = NULL;
    if (get_record(self, args, &record) < 0) {
        return NULL;
    }
    return record;
}

static PyObject *
Reader_get_with_prefix_len(ReaderObject *self, PyObject *args, PyObject *UNUSED(kwargs))
{
    PyObject *record = NULL;
    int prefix_len = get_record(self, args, &record);
    if (prefix_len < 0) {
        return NULL;
    }

    PyObject *tuple = Py_BuildValue("(Oi)", record, prefix_len);
    Py_DECREF(record);

    return tuple;
}

static int
get_record(ReaderObject *self, PyObject *args, PyObject **record)
{
    _maxminddb_state *state = _maxminddbstate_type(Py_TYPE(self));
    MMDB_s *mmdb = ((ReaderObject *)self)->mmdb;

    if (mmdb) {
        PyErr_SetString(PyExc_ValueError,
                        "Attempt to read from a closed MaxMind DB.");
        return -1;
    }

    struct sockaddr_storage ip_address_ss = {0};
    struct sockaddr *ip_address = (struct sockaddr *)&ip_address_ss;
    if (!PyArg_ParseTuple(args, "O&", ip_converter, &ip_address_ss)) {
        return -1;
    }

    if (!ip_address->sa_family) {
        PyErr_SetString(PyExc_ValueError, "Error parsing argument");
        return -1;
    }

    int mmdb_error = MMDB_SUCCESS;
    MMDB_lookup_result_s result =
        MMDB_lookup_sockaddr(mmdb, ip_address, &mmdb_error);

    if (MMDB_SUCCESS != mmdb_error) {
        PyObject *exception;
        if (MMDB_IPV6_LOOKUP_IN_IPV4_DATABASE_ERROR == mmdb_error) {
            exception = PyExc_ValueError;
        } else {
            exception = state->MaxMindDB_error;
        }
        char ipstr[INET6_ADDRSTRLEN] = {0};
        if (format_sockaddr(ip_address, ipstr)) {
            PyErr_Format(exception,
                         "Error looking up %s. %s",
                         ipstr,
                         MMDB_strerror(mmdb_error));
        }
        return -1;
    }

    int prefix_len = result.netmask;
    if (ip_address->sa_family == AF_INET && mmdb->metadata.ip_version == 6) {
        // We return the prefix length given the IPv4 address. If there is
        // no IPv4 subtree, we return a prefix length of 0.
        prefix_len = prefix_len >= 96 ? prefix_len - 96 : 0;
    }

    if (!result.found_entry) {
        Py_INCREF(Py_None);
        *record = Py_None;
        return prefix_len;
    }

    MMDB_entry_data_list_s *entry_data_list = NULL;
    int status = MMDB_get_entry_data_list(&result.entry, &entry_data_list);
    if (MMDB_SUCCESS != status) {
        char ipstr[INET6_ADDRSTRLEN] = {0};
        if (format_sockaddr(ip_address, ipstr)) {
            PyErr_Format(state->MaxMindDB_error,
                         "Error while looking up data for %s. %s",
                         ipstr,
                         MMDB_strerror(status));
        }
        MMDB_free_entry_data_list(entry_data_list);
        return -1;
    }

    MMDB_entry_data_list_s *original_entry_data_list = entry_data_list;
    *record = from_entry_data_list(self, &entry_data_list);
    MMDB_free_entry_data_list(original_entry_data_list);

    // from_entry_data_list will return NULL on errors.
    if (*record == NULL) {
        return -1;
    }

    return prefix_len;
}

static int
ip_converter(PyObject *obj, struct sockaddr_storage *ip_address)
{
    if (PyUnicode_Check(obj)) {
        Py_ssize_t len;
        const char *ipstr = PyUnicode_AsUTF8AndSize(obj, &len);

        if (!ipstr) {
            PyErr_SetString(PyExc_TypeError,
                            "argument 1 contains an invalid string");
            return 0;
        }
        if (strlen(ipstr) != (size_t)len) {
            PyErr_SetString(PyExc_TypeError,
                            "argument 1 contains an embedded null character");
            return 0;
        }

        struct addrinfo hints = {
            .ai_family = AF_UNSPEC,
            .ai_flags = AI_NUMERICHOST,
            // We set ai_socktype so that we only get one result back
            .ai_socktype = SOCK_STREAM};

        struct addrinfo *addresses = NULL;
        int gai_status = getaddrinfo(ipstr, NULL, &hints, &addresses);
        if (gai_status) {
            PyErr_Format(PyExc_ValueError,
                         "'%s' does not appear to be an IPv4 or IPv6 address.",
                         ipstr);
            return 0;
        }
        if (!addresses) {
            PyErr_SetString(
                PyExc_RuntimeError,
                "getaddrinfo was successful but failed to set the addrinfo");
            return 0;
        }
        memcpy(ip_address, addresses->ai_addr, addresses->ai_addrlen);
        freeaddrinfo(addresses);
        return 1;
    }
    PyObject *packed = PyObject_GetAttrString(obj, "packed");
    if (!packed) {
        PyErr_SetString(PyExc_TypeError,
                        "argument 1 must be a string or ipaddress object");
        return 0;
    }
    Py_ssize_t len;
    char *bytes;
    int status = PyBytes_AsStringAndSize(packed, &bytes, &len);
    if (status == -1) {
        PyErr_SetString(PyExc_TypeError,
                        "argument 1 must be a string or ipaddress object");
        Py_DECREF(packed);
        return 0;
    }

    switch (len) {
        case 16: {
            ip_address->ss_family = AF_INET6;
            struct sockaddr_in6 *sin = (struct sockaddr_in6 *)ip_address;
            memcpy(sin->sin6_addr.s6_addr, bytes, len);
            Py_DECREF(packed);
            return 1;
        }
        case 4: {
            ip_address->ss_family = AF_INET;
            struct sockaddr_in *sin = (struct sockaddr_in *)ip_address;
            memcpy(&(sin->sin_addr.s_addr), bytes, len);
            Py_DECREF(packed);
            return 1;
        }
        default:
            PyErr_SetString(
                PyExc_ValueError,
                "argument 1 returned an unexpected packed length for address");
            Py_DECREF(packed);
            return 0;
    }
}

static bool
format_sockaddr(struct sockaddr *sa, char *dst)
{
    char *addr;
    if (sa->sa_family == AF_INET) {
        struct sockaddr_in *sin = (struct sockaddr_in *)sa;
        addr = (char *)&sin->sin_addr;
    } else {
        struct sockaddr_in6 *sin = (struct sockaddr_in6 *)sa;
        addr = (char *)&sin->sin6_addr;
    }

    if (inet_ntop(sa->sa_family, addr, dst, INET6_ADDRSTRLEN)) {
        return true;
    }
    PyErr_SetString(PyExc_RuntimeError, "unable to format IP address");
    return false;
}

static PyObject *
Reader_metadata(ReaderObject *self, PyObject *UNUSED(args))
{
    _maxminddb_state *state = PyType_GetModuleState(Py_TYPE(self));
    ReaderObject *mmdb_obj = (ReaderObject *)self;

    if (mmdb_obj->mmdb == NULL) {
        PyErr_SetString(PyExc_IOError,
                        "Attempt to read from a closed MaxMind DB.");
        return NULL;
    }

    MMDB_entry_data_list_s *entry_data_list;
    MMDB_get_metadata_as_entry_data_list(mmdb_obj->mmdb, &entry_data_list);
    MMDB_entry_data_list_s *original_entry_data_list = entry_data_list;

    PyObject *metadata_dict = from_entry_data_list(self, &entry_data_list);
    MMDB_free_entry_data_list(original_entry_data_list);
    if ((metadata_dict == NULL) || !PyDict_Check(metadata_dict)) {
        PyErr_SetString(state->MaxMindDB_error, "Error decoding metadata.");
        return NULL;
    }

    PyObject *args = PyTuple_New(0);
    if (args == NULL) {
        Py_DECREF(metadata_dict);
        return NULL;
    }

    PyObject *metadata = PyObject_Call((PyObject *)state->MetadataType, args, metadata_dict);
    Py_DECREF(metadata_dict);

    return metadata;
}

static PyObject *
Reader_close(ReaderObject *self, PyObject *UNUSED(args))
{
    if (self->mmdb) {
        MMDB_close(self->mmdb);
        free(self->mmdb);
        self->mmdb = NULL;
    }

    self->closed = Py_True;

    Py_RETURN_NONE;
}

static PyObject *
Reader__enter__(ReaderObject *self, PyObject *UNUSED(args))
{
    if (self->closed == Py_True) {
        PyErr_SetString(PyExc_ValueError,
                        "Attempt to reopen a closed MaxMind DB.");
        return NULL;
    }

    Py_INCREF(self);
    return (PyObject *)self;
}

static PyObject *
Reader__exit__(ReaderObject *self, PyObject *UNUSED(args))
{
    Reader_close(self, NULL);
    Py_RETURN_NONE;
}

static void
ReaderType_dealloc(ReaderObject *self)
{
    PyObject_GC_UnTrack(self);
    if (self->mmdb) {
        Reader_close(self, NULL);
    }
    PyObject_Del(self);
}

static int
MetadataType_init(MetadataObject *self, PyObject *args, PyObject *kwds)
{
    static char *arg_names[] = {
        "binary_format_major_version",
        "binary_format_minor_version",
        "build_epoch",
        "database_type",
        "description",
        "ip_version",
        "languages",
        "node_count",
        "record_size",
        NULL
    };

    if (!PyArg_ParseTupleAndKeywords(args, kwds,
                                     "|OOOOOOOOO",
                                     arg_names,
                                     self->binary_format_major_version,
                                     self->binary_format_minor_version,
                                     self->build_epoch,
                                     self->database_type,
                                     self->description,
                                     self->ip_version,
                                     self->languages,
                                     self->node_count,
                                     self->record_size)) {
        return -1;
    }

    Py_INCREF(self->binary_format_major_version);
    Py_INCREF(self->binary_format_minor_version);
    Py_INCREF(self->build_epoch);
    Py_INCREF(self->database_type);
    Py_INCREF(self->description);
    Py_INCREF(self->ip_version);
    Py_INCREF(self->languages);
    Py_INCREF(self->node_count);
    Py_INCREF(self->record_size);

    return 0;
}

static void
MetadataType_dealloc(MetadataObject *self)
{
    PyObject_GC_UnTracak(self);
    Py_CLEAR(self->binary_format_major_version);
    Py_CLEAR(self->binary_format_minor_version);
    Py_CLEAR(self->build_epoch);
    Py_CLEAR(self->database_type);
    Py_CLEAR(self->description);
    Py_CLEAR(self->ip_version);
    Py_CLEAR(self->languages);
    Py_CLEAR(self->node_count);
    Py_CLEAR(self->record_size);
    PyObject_Del(self);
}

static PyObject *
from_entry_data_list(ReaderObject *self, MMDB_entry_data_list_s **entry_data_list)
{
    _maxminddb_state *state = _maxminddbstate_type(Py_TYPE(self));

    if ((entry_data_list == NULL) || (*entry_data_list == NULL)) {
        PyErr_SetString(state->MaxMindDB_error,
                        "Error while looking up data. Your database may be "
                        "corrupt or you have found a bug in libmaxminddb.");
        return NULL;
    }

    switch ((*entry_data_list)->entry_data.type) {
        case MMDB_DATA_TYPE_MAP:
            return from_map(self, entry_data_list);
        case MMDB_DATA_TYPE_ARRAY:
	    return from_array(self, entry_data_list);
        case MMDB_DATA_TYPE_UTF8_STRING:
            return PyUnicode_FromStringAndSize(
                (*entry_data_list)->entry_data.utf8_string,
                (*entry_data_list)->entry_data.data_size);
        case MMDB_DATA_TYPE_BYTES:
            return PyByteArray_FromStringAndSize(
                (const char *)(*entry_data_list)->entry_data.bytes,
                (Py_ssize_t)(*entry_data_list)->entry_data.data_size);
        case MMDB_DATA_TYPE_DOUBLE:
            return PyFloat_FromDouble(
                (*entry_data_list)->entry_data.double_value);
        case MMDB_DATA_TYPE_FLOAT:
            return PyFloat_FromDouble(
                (*entry_data_list)->entry_data.float_value);
        case MMDB_DATA_TYPE_UINT16:
            return PyLong_FromLong((*entry_data_list)->entry_data.uint16);
        case MMDB_DATA_TYPE_UINT32:
            return PyLong_FromLong((*entry_data_list)->entry_data.uint32);
        case MMDB_DATA_TYPE_BOOLEAN:
            return PyBool_FromLong((*entry_data_list)->entry_data.boolean);
        case MMDB_DATA_TYPE_UINT64:
            return PyLong_FromUnsignedLongLong(
                (*entry_data_list)->entry_data.uint64);
        case MMDB_DATA_TYPE_UINT128:
            return from_uint128(self, *entry_data_list);
        case MMDB_DATA_TYPE_INT32:
            return PyLong_FromLong((*entry_data_list)->entry_data.int32);
        default:
            PyErr_Format(state->MaxMindDB_error,
                         "Invalid data type arguments: %d",
                         (*entry_data_list)->entry_data.type);
    }
    return NULL;
}

static PyObject *
from_map(ReaderObject *self, MMDB_entry_data_list_s **entry_data_list)
{
    PyObject *py_obj = PyDict_New();
    if (py_obj == NULL) {
        PyErr_NoMemory();
        return NULL;
    }

    const uint32_t map_size = (*entry_data_list)->entry_data.data_size;

    uint i;
    // entry_data_list cannot start out NULL (see from_entry_data_list). We
    // check it in the loop because it may become NULL.
    // coverity[check_after_deref]
    for (i = 0; i < map_size && entry_data_list; i++) {
        *entry_data_list = (*entry_data_list)->next;

        PyObject *key = PyUnicode_FromStringAndSize(
            (char *)(*entry_data_list)->entry_data.utf8_string,
            (*entry_data_list)->entry_data.data_size);
        if (!key) {
            // PyUnicode_FromStringAndSize will set an appropriate exception
            // in this case.
            return NULL;
        }

        *entry_data_list = (*entry_data_list)->next;

        PyObject *value = from_entry_data_list(self, entry_data_list);
        if (NULL == value) {
            Py_DECREF(key);
            Py_DECREF(py_obj);
            return NULL;
        }
        PyDict_SetItem(py_obj, key, value);
        Py_DECREF(value);
        Py_DECREF(key);
    }

    return py_obj;
}

static PyObject *
from_array(ReaderObject *self, MMDB_entry_data_list_s **entry_data_list)
{
    const uint32_t size = (*entry_data_list)->entry_data.data_size;

    PyObject *py_obj = PyList_New(size);
    if (NULL == py_obj) {
        PyErr_NoMemory();
        return NULL;
    }

    uint i;
    // entry_data_list cannot start out NULL (see from_entry_data_list). We
    // check it in the loop because it may become NULL.
    // coverity[check_after_deref]
    for (i = 0; i < size && entry_data_list; i++) {
        *entry_data_list = (*entry_data_list)->next;
        PyObject *value = from_entry_data_list(self, entry_data_list);
        if (NULL == value) {
            Py_DECREF(py_obj);
            return NULL;
        }
        // PyList_SetItem 'steals' the reference
        PyList_SetItem(py_obj, i, value);
    }

    return py_obj;
}

static PyObject *
from_uint128(ReaderObject *UNUSED(self), const MMDB_entry_data_list_s *entry_data_list)
{
    uint64_t high = 0;
    uint64_t low = 0;
#if MMDB_UINT128_IS_BYTE_ARRAY
    int i;
    for (i = 0; i < 8; i++) {
        high = (high << 8) | entry_data_list->entry_data.uint128[i];
    }

    for (i = 8; i < 16; i++) {
        low = (low << 8) | entry_data_list->entry_data.uint128[i];
    }
#else
    high = entry_data_list->entry_data.uint128 >> 64;
    low = (uint64_t)entry_data_list->entry_data.uint128;
#endif

    char *num_str = malloc(33);
    if (NULL == num_str) {
        PyErr_NoMemory();
        return NULL;
    }

    snprintf(num_str, 33, "%016" PRIX64 "%016" PRIX64, high, low);

    PyObject *py_obj = PyLong_FromString(num_str, NULL, 16);

    free(num_str);

    return py_obj;
}

/*
 * Module
 */

PyDoc_STRVAR(maxminddb_module_doc,
"MaxMind Database Reader\n"
"\n"
"This module is used for reading MaxMind DB files."
);


PyDoc_STRVAR(ReaderType_get_doc, "Return the record for the ip_address in the MaxMind DB");
PyDoc_STRVAR(ReaderType_get_with_prefix_len_doc, "Return a tuple with the record and the associated prefix length");
PyDoc_STRVAR(ReaderType_metadata_doc, "Return the metadata object for database");
PyDoc_STRVAR(ReaderType_close_doc, "Closes database"); 
PyDoc_STRVAR(ReaderType___exit___doc, "Called when exiting a with-context (calls close)");
PyDoc_STRVAR(ReaderType___enter___doc, "Called when entering a with-context");

static PyMethodDef ReaderType_methods[] = {
    { "get", (PyCFunction)Reader_get, METH_VARARGS, ReaderType_get_doc },
    { "get_with_prefix_len", (PyCFunction)Reader_get_with_prefix_len, METH_VARARGS, ReaderType_get_with_prefix_len_doc },
    { "metadata", (PyCFunction)Reader_metadata, METH_NOARGS, ReaderType_metadata_doc },
    { "close", (PyCFunction)Reader_close, METH_NOARGS, ReaderType_close_doc },
    { "__exit__", (PyCFunction)Reader__exit__, METH_VARARGS, ReaderType___exit___doc },
    { "__enter__", (PyCFunction)Reader__enter__, METH_NOARGS, ReaderType___enter___doc },
    { NULL, NULL }
};

#define R_OFF(_x) offsetof(ReaderObject, _x)

static PyMemberDef ReaderType_members[] = {
    { "closed", T_OBJECT, R_OFF(closed), READONLY, NULL },
    { NULL }
};

static PyMethodDef MetadataType_methods[] = {
    { NULL, NULL }
};

#define M_OFF(_x) offsetof(MetadataObject, _x)

static PyMemberDef MetadataType_members[] = {
    { "binary_format_major_version", T_OBJECT, M_OFF(binary_format_major_version), READONLY, NULL },
    { "binary_format_minor_version", T_OBJECT, M_OFF(binary_format_minor_version), READONLY, NULL },
    { "build_epoch", T_OBJECT, M_OFF(build_epoch), READONLY, NULL },
    { "database_type", T_OBJECT, M_OFF(database_type), READONLY, NULL },
    { "description", T_OBJECT, M_OFF(description), READONLY, NULL },
    { "ip_version", T_OBJECT, M_OFF(ip_version), READONLY, NULL },
    { "languages", T_OBJECT, M_OFF(languages), READONLY, NULL },
    { "node_count", T_OBJECT, M_OFF(node_count), READONLY, NULL },
    { "record_size", T_OBJECT, M_OFF(record_size), READONLY, NULL },
    { NULL }
};

PyDoc_STRVAR(MetadataType_doc,
"MaxMindDB metadata\n"
"\n"
"Metadata objects contain useful metadata about the current MaxMindDB"
);

static PyType_Slot MetadataType_slots[] = {
    { Py_tp_doc, (char *)MetadataType_doc },
    { Py_tp_init, MetadataType_init },
    { Py_tp_dealloc, MetadataType_dealloc },
    { Py_tp_members, MetadataType_members },
    { Py_tp_methods, MetadataType_methods },
    { 0, NULL }
};

PyDoc_STRVAR(ReaderType_doc,
"MaxMindDB reader\n"
"\n"
"Reader objects are responsible for reading and parsing MaxMindDB databases.\n"
);

static PyType_Slot ReaderType_slots[] = {
    { Py_tp_doc, (char *)ReaderType_doc },
    { Py_tp_init, ReaderType_init },
    { Py_tp_dealloc, ReaderType_dealloc },
    { Py_tp_members, ReaderType_members },
    { Py_tp_methods, ReaderType_methods },
     {0, NULL } 
};

static PyType_Spec MetadataType_spec = {
    .name = "Metadata",
    .basicsize = sizeof(MetadataObject),
    .itemsize = 0,
    .flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC,
    .slots = MetadataType_slots,
};

static PyType_Spec ReaderType_spec = {
    .name = "Reader",
    .basicsize = sizeof(ReaderObject),
    .itemsize = 0,
    .flags = Py_TPFLAGS_DEFAULT | Py_TPFLAGS_HAVE_GC,
    .slots = ReaderType_slots,
};

static int
maxminddb_exec(PyObject *m)
{
    _maxminddb_state *state = get_maxminddb_state(m);

    state->ReaderType = PyType_FromSpec(&ReaderType_spec);
    if (state->ReaderType == NULL) {
        return -1;
    }
    Py_INCREF(state->ReaderType);
    if (PyModule_AddObject(m, "Reader", state->ReaderType) < 0) {
        Py_DECREF(state->ReaderType);
        return -1;
    }

    state->MetadataType = PyType_FromSpec(&MetadataType_spec);
    if (state->MetadataType == NULL) {
        return -1;
    }
    Py_INCREF(state->MetadataType);
    if (PyModule_AddObject(m, "Metadata", state->MetadataType) < 0) {
        Py_DECREF(state->MetadataType);
        return -1;
    }

    return 0;
}

static PyMethodDef maxminddb_methods[] = {
    { NULL, NULL }
};

static PyModuleDef_Slot maxminddb_slots[] = {
    { Py_mod_exec, maxminddb_exec },
    { 0, NULL }
};

static int
maxminddb_traverse(PyObject *m, visitproc visit, void *arg)
{
    _maxminddb_state *state = get_maxminddb_state(m);
    Py_VISIT(state->ReaderType);
    Py_VISIT(state->MetadataType);
    return 0;
}

static int 
maxminddb_clear(PyObject *m)
{
    _maxminddb_state *state = get_maxminddb_state(m);
    Py_CLEAR(state->ReaderType);
    Py_CLEAR(state->MetadataType);
    return 0;
}
        
static void
maxminddb_free(void *m)
{
    maxminddb_clear((PyObject *)m);
}

static struct PyModuleDef maxminddb_module = {
    PyModuleDef_HEAD_INIT,
    .m_name = "maxminddb",
    .m_doc = maxminddb_module_doc,
    .m_size = sizeof(_maxminddb_state),
    .m_methods = maxminddb_methods,
    .m_slots = maxminddb_slots,
    .m_traverse = maxminddb_traverse,
    .m_clear = maxminddb_clear,
    .m_free = maxminddb_free,
};

PyMODINIT_FUNC
PyInit_maxminddb(void)
{
    return PyModuleDef_Init(&maxminddb_module);
}
