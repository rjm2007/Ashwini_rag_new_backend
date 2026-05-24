import {
  BadRequestException,
  Controller,
  Get,
  Param,
  Post,
  Query,
  Req,
  UploadedFile,
  UseGuards,
  UseInterceptors
} from "@nestjs/common";
import { FileInterceptor } from "@nestjs/platform-express";
import { Request } from "express";
import { Roles } from "../../common/decorators/roles.decorator";
import { RolesGuard } from "../../common/guards/roles.guard";
import { UserRole } from "../../common/enums/user-role.enum";
import { DocumentsService } from "./documents.service";
import { ListDocumentsDto } from "./dto/list-documents.dto";

@Controller("documents")
@UseGuards(RolesGuard)
export class DocumentsController {
  constructor(private readonly documentsService: DocumentsService) {}

  @Post("upload")
  @Roles(UserRole.ADMIN)
  @UseInterceptors(FileInterceptor("file"))
  async upload(@UploadedFile() file: Express.Multer.File, @Req() req: Request & { user?: any }) {
    // This function validates a PDF file and delegates upload flow.
    if (!file) {
      throw new BadRequestException("Missing file");
    }
    if (file.mimetype !== "application/pdf") {
      throw new BadRequestException("Only PDF files are allowed");
    }
    if (file.size > 50 * 1024 * 1024) {
      throw new BadRequestException("File exceeds 50MB limit");
    }
    return this.documentsService.uploadDocument(file, req.user?.userId);
  }

  @Get()
  async list(@Query() query: ListDocumentsDto) {
    // This function returns paginated documents.
    return this.documentsService.listDocuments(query);
  }

  @Get(":id")
  async getById(@Param("id") id: string) {
    // This function returns a single document by id.
    return this.documentsService.getDocument(id);
  }

  @Get(":id/pdf-url")
  async getPdfUrl(@Param("id") id: string) {
    // This function returns signed PDF URL.
    return this.documentsService.getPdfSignedUrl(id);
  }
}
