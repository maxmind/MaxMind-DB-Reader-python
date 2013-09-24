#include <Python.h>
#include <maxminddb.h>


static PyTypeObject Reader_Type;
static PyTypeObject Metadata_Type;
static PyObject *MaxMindDB_error;

typedef struct {
    PyObject_HEAD               /* no semicolon */
    MMDB_s * mmdb;
} Reader_obj;

typedef struct {
    PyObject_HEAD               /* no semicolon */
    PyObject *metadata;
} Metadata_obj;

static const MMDB_entry_data_list_s *handle_entry_data_list(
    const MMDB_entry_data_list_s *entry_data_list,
    PyObject **py_obj);
static const MMDB_entry_data_list_s *handle_map(
    const MMDB_entry_data_list_s *entry_data_list,
    PyObject **py_obj);
static const MMDB_entry_data_list_s *handle_array(
    const MMDB_entry_data_list_s *entry_data_list,
    PyObject **py_obj);
static void handle_uint128(const MMDB_entry_data_list_s *entry_data_list,
                           PyObject **py_obj);
static void handle_uint64(const MMDB_entry_data_list_s *entry_data_list,
                          PyObject **py_obj);
static bool file_is_readable(const char *filename);

#if PY_MAJOR_VERSION >= 3
    #define MOD_INIT(name) PyMODINIT_FUNC PyInit_ ## name(void)
    #define RETURN_MOD_INIT(m) return (m)
#else
    #define MOD_INIT(name) PyMODINIT_FUNC init ## name(void)
    #define RETURN_MOD_INIT(m) return
    #define PyInt_FromLong PyLong_FromLong
#endif

#ifdef __GNUC__
    #  define UNUSED(x) UNUSED_ ## x __attribute__((__unused__))
#else
    #  define UNUSED(x) UNUSED_ ## x
#endif

static PyObject *Reader_constructor(PyObject *UNUSED(self), PyObject * args)
{
    char *filename;

    if (!PyArg_ParseTuple(args, "s", &filename)) {
        return NULL;
    }

    if (!file_is_readable(filename)) {
        PyErr_Format(PyExc_ValueError,
                     "The file \"%s\" does not exist or is not readable.",
                     filename);
        return NULL;
    }

    Reader_obj *obj = PyObject_New(Reader_obj, &Reader_Type);
    if (!obj) {
        return NULL;
    }

    MMDB_s *mmdb = (MMDB_s *)malloc(sizeof(MMDB_s));
    if (NULL == mmdb) {
        PyErr_NoMemory();
    }
    uint16_t status = MMDB_open(filename, MMDB_MODE_MMAP, mmdb);

    if (MMDB_SUCCESS != status) {
        free(mmdb);
        return PyErr_Format(
                   MaxMindDB_error,
                   "Error opening database file (%s). Is this a valid MaxMind DB file?",
                   filename
                   );
    }

    obj->mmdb = mmdb;
    return (PyObject *)obj;
}

static PyObject *Reader_get(PyObject * self, PyObject * args)
{
    char *ip_address = NULL;

    Reader_obj *mmdb_obj = (Reader_obj *)self;
    if (!PyArg_ParseTuple(args, "s", &ip_address)) {
        return NULL;
    }

    MMDB_s *mmdb = mmdb_obj->mmdb;

    if (NULL == mmdb) {
        PyErr_SetString(PyExc_IOError,
                        "Attempt to read from a closed MaxMind DB.");
        return NULL;
    }

    int gai_error = MMDB_SUCCESS;
    int mmdb_error = MMDB_SUCCESS;
    MMDB_lookup_result_s result =
        MMDB_lookup_string(mmdb, ip_address, &gai_error,
                           &mmdb_error);

    if (MMDB_SUCCESS != gai_error) {
        PyErr_Format(PyExc_ValueError,
                     "The value \"%s\" is not a valid IP address.",
                     ip_address);
        return NULL;
    }

    if (MMDB_SUCCESS != mmdb_error) {
        PyErr_Format(MaxMindDB_error, "Error looking up %s", ip_address);
        return NULL;
    }

    MMDB_entry_data_list_s *entry_data_list = NULL;

    if (result.found_entry) {
        PyObject *py_obj = NULL;

        int status = MMDB_get_entry_data_list(&result.entry, &entry_data_list);
        if (MMDB_SUCCESS != status) {
            PyErr_Format(MaxMindDB_error,
                         "Error while looking up data for %s", ip_address);
        } else if (NULL != entry_data_list) {
            handle_entry_data_list(entry_data_list, &py_obj);
        }

        MMDB_free_entry_data_list(entry_data_list);
        return py_obj;
    }

    Py_RETURN_NONE;
}

static PyObject *Reader_metadata(PyObject *self, PyObject *UNUSED(args))
{
    Reader_obj *mmdb_obj = (Reader_obj *)self;

    if (NULL == mmdb_obj->mmdb) {
        PyErr_SetString(PyExc_IOError,
                        "Attempt to read from a closed MaxMind DB.");
        return NULL;
    }

    Metadata_obj *obj = PyObject_New(Metadata_obj, &Metadata_Type);
    if (!obj) {
        return NULL;
    }

    PyObject *metadata_dict;

    MMDB_entry_data_list_s *entry_data_list;
    MMDB_get_metadata_as_entry_data_list(mmdb_obj->mmdb, &entry_data_list);

    handle_entry_data_list(entry_data_list, &metadata_dict);
    MMDB_free_entry_data_list(entry_data_list);

    obj->metadata = metadata_dict;
    Py_INCREF(metadata_dict);

    return (PyObject *)obj;
}

static PyObject *Reader_close(PyObject * self, PyObject *UNUSED(args))
{
    Reader_obj *mmdb_obj = (Reader_obj *)self;

    if (NULL == mmdb_obj->mmdb) {
        PyErr_SetString(PyExc_IOError,
                        "Attempt to close a closed MaxMind DB.");
        return NULL;
    }
    MMDB_close(mmdb_obj->mmdb);
    free(mmdb_obj->mmdb);
    mmdb_obj->mmdb = NULL;

    Py_RETURN_NONE;
}

static void Reader_dealloc(PyObject * self)
{
    Reader_obj *obj = (Reader_obj *)self;
    if (NULL != obj->mmdb) {
        Reader_close(self, NULL);
    }

    PyObject_Del(self);
}

static PyObject *Metadata_GetAttr(PyObject *self, PyObject *name )
{
    Metadata_obj *metadata_obj = (Metadata_obj *)self;

    PyObject *prop = PyDict_GetItem(metadata_obj->metadata, name);
    if (NULL == prop) {
        PyObject *byte_name = PyUnicode_AsUTF8String(name);
        char *attribute = PyBytes_AsString(byte_name);
        PyErr_Format(PyExc_AttributeError,
                     "'maxminddb.Metadata' object has no attribute '%s'",
                     attribute);
        Py_DECREF(byte_name);
    }
    return prop;
}

static void Metadata_dealloc(PyObject * self)
{
    Metadata_obj *obj = (Metadata_obj *)self;
    Py_DECREF(obj->metadata);
    PyObject_Del(self);
}

static const MMDB_entry_data_list_s *handle_entry_data_list(
    const MMDB_entry_data_list_s *entry_data_list,
    PyObject **py_obj)
{
    switch (entry_data_list->entry_data.type) {
    case MMDB_DATA_TYPE_MAP:
        return handle_map(entry_data_list, py_obj);
    case MMDB_DATA_TYPE_ARRAY:
        return handle_array(entry_data_list, py_obj);
    case MMDB_DATA_TYPE_UTF8_STRING:
        *py_obj = PyUnicode_FromStringAndSize(
            entry_data_list->entry_data.utf8_string,
            entry_data_list->entry_data.data_size
            );
        break;
    case MMDB_DATA_TYPE_BYTES:
        *py_obj = PyByteArray_FromStringAndSize(
            (const char *)entry_data_list->entry_data.bytes,
            (Py_ssize_t)entry_data_list->entry_data.data_size);
        break;
    case MMDB_DATA_TYPE_DOUBLE:
        *py_obj = PyFloat_FromDouble(entry_data_list->entry_data.double_value);
        break;
    case MMDB_DATA_TYPE_FLOAT:
        *py_obj = PyFloat_FromDouble(entry_data_list->entry_data.float_value);
        break;
    case MMDB_DATA_TYPE_UINT16:
        *py_obj = PyLong_FromLong( entry_data_list->entry_data.uint16);
        break;
    case MMDB_DATA_TYPE_UINT32:
        *py_obj = PyLong_FromLong(entry_data_list->entry_data.uint32);
        break;
    case MMDB_DATA_TYPE_BOOLEAN:
        *py_obj = PyBool_FromLong(entry_data_list->entry_data.boolean);
        break;
    case MMDB_DATA_TYPE_UINT64:
        handle_uint64(entry_data_list, py_obj);
        break;
    case MMDB_DATA_TYPE_UINT128:
        handle_uint128(entry_data_list, py_obj);
        break;
    case MMDB_DATA_TYPE_INT32:
        *py_obj = PyLong_FromLong(entry_data_list->entry_data.int32);
        break;
    default:
        PyErr_Format(MaxMindDB_error,
                     "Invalid data type arguments: %d",
                     entry_data_list->entry_data.type);
        return NULL;
    }
    return entry_data_list->next;
}

static const MMDB_entry_data_list_s *handle_map(
    const MMDB_entry_data_list_s *entry_data_list,
    PyObject **py_obj)
{
    *py_obj = PyDict_New();

    const uint32_t map_size = entry_data_list->entry_data.data_size;
    entry_data_list = entry_data_list->next;

    uint i;
    for (i = 0; i < map_size && entry_data_list; i++) {
        PyObject *key, *value;

        key = PyUnicode_FromStringAndSize(
            (char *)entry_data_list->entry_data.utf8_string,
            entry_data_list->entry_data.data_size
            );

        entry_data_list = entry_data_list->next;

        entry_data_list = handle_entry_data_list(entry_data_list,
                                                 &value);
        PyDict_SetItem(*py_obj, key, value);
        Py_DECREF(value);
        Py_DECREF(key);
    }
    return entry_data_list;
}

static const MMDB_entry_data_list_s *handle_array(
    const MMDB_entry_data_list_s *entry_data_list,
    PyObject **py_obj)
{
    const uint32_t size = entry_data_list->entry_data.data_size;

    *py_obj = PyList_New(size);
    entry_data_list = entry_data_list->next;

    uint i;
    for (i = 0; i < size && entry_data_list; i++) {
        PyObject *new_value;
        entry_data_list = handle_entry_data_list(entry_data_list,
                                                 &new_value);
        PyList_SET_ITEM(*py_obj, i, new_value);
    }
    return entry_data_list;
}

static void handle_uint128(const MMDB_entry_data_list_s *entry_data_list,
                           PyObject **py_obj)
{
    uint64_t high = 0;
    uint64_t low = 0;
#if MISSING_UINT128
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

    char *num_str;
    int status = asprintf(&num_str, "0x%016" PRIX64 "%016" PRIX64, high, low);

    if (status <= 0) {
        PyErr_NoMemory();
    }

    *py_obj = PyLong_FromString(num_str, NULL, 0);

    free(num_str);
}

static void handle_uint64(const MMDB_entry_data_list_s *entry_data_list,
                          PyObject **py_obj)
{
    char *int_str;
    int status = asprintf(&int_str, "%" PRIu64,
                          entry_data_list->entry_data.uint64 );
    if (status <= 0) {
        PyErr_NoMemory();
    }

    *py_obj = PyLong_FromString(int_str, NULL, 10);
    free(int_str);
}

static bool file_is_readable(const char *filename)
{
    FILE *file = fopen(filename, "r");
    if (file) {
        fclose(file);
        return true;
    }
    return false;
}

static PyMethodDef Reader_methods[] = {
    { "get",      Reader_get,      METH_VARARGS,
      "Get record for IP address" },
    { "metadata", Reader_metadata, METH_NOARGS,
      "Returns metadata object for database" },
    { "close",    Reader_close,    METH_NOARGS, "Closes database"},
    { NULL,       NULL,            0,           NULL        }
};

static PyTypeObject Reader_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_basicsize = sizeof(Reader_obj),
    .tp_dealloc = Reader_dealloc,
    .tp_doc = "maxminddb.Reader object",
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_methods = Reader_methods,
    .tp_name = "maxminddb.Reader",
};

static PyMethodDef Metadata_methods[] = {
    { NULL, NULL, 0, NULL }
};

static PyTypeObject Metadata_Type = {
    PyVarObject_HEAD_INIT(NULL, 0)
    .tp_basicsize = sizeof(Metadata_obj),
    .tp_dealloc = Metadata_dealloc,
    .tp_doc = "maxminddb.Metadata object",
    .tp_flags = Py_TPFLAGS_DEFAULT,
    .tp_getattro = Metadata_GetAttr,
    .tp_methods = Metadata_methods,
    .tp_name = "maxminddb.Metadata",
};

static PyMethodDef MaxMindDB_methods[] = {
    { "Reader", Reader_constructor, 1,
      "Creates a new maxminddb.Reader object" },
    { NULL,     NULL,               0,NULL}
};

#if PY_MAJOR_VERSION >= 3
static struct PyModuleDef MaxMindDB_module = {
    PyModuleDef_HEAD_INIT,
    .m_name = "maxminddb",
    .m_doc = "This is a module to read MaxMind DB file format",
    .m_methods = MaxMindDB_methods,
};
#endif

static void init_type(PyObject *m, PyTypeObject *type)
{
    Metadata_Type.tp_new = PyType_GenericNew;

    if (PyType_Ready(type) == 0) {
        Py_INCREF(type);
        PyModule_AddObject(m, "maxminddb", (PyObject *)type);
    }
}

MOD_INIT(maxminddb){
    PyObject *m;

    m = PyModule_Create(&MaxMindDB_module);
    if (m == NULL) {
        return NULL;
    }

    init_type(m, &Reader_Type);
    init_type(m, &Metadata_Type);

    MaxMindDB_error = PyErr_NewException("maxminddb.InvalidDatabaseError", NULL,
                                         NULL);
    Py_INCREF(MaxMindDB_error);
    PyModule_AddObject(m, "InvalidDatabaseError", MaxMindDB_error);

    RETURN_MOD_INIT(m);
}
