import { BadRequestException, Injectable, Logger, NotFoundException } from "@nestjs/common";
import { InjectRepository } from "@nestjs/typeorm";
import { SendMessageCommand } from "@aws-sdk/client-sqs";
import { ILike, Repository } from "typeorm";
import { v4 as uuidv4 } from "uuid";
import { sqsClient } from "../../config/aws.config";
import { DocumentEntity } from "./entities/document.entity";
import { DocumentRepository, ProcessingStatus } from "./entities/document-status.enum";
import { S3Service } from "./s3.service";
import { ListDocumentsDto } from "./dto/list-documents.dto";

@Injectable()
export class DocumentsService {
  private readonly logger = new Logger(DocumentsService.name);

  constructor(
    @InjectRepository(DocumentEntity)
    private readonly documentsRepository: Repository<DocumentEntity>,
    private readonly s3Service: S3Service
  ) {}

  async uploadDocument(file: Express.Multer.File, userId: string) {
    const normalizedName = file.originalname.trim();
    const duplicate = await this.documentsRepository.findOne({
      where: {
        originalFilename: ILike(normalizedName)
      },
      order: {
        uploadedAt: "DESC"
      }
    });
    if (duplicate) {
      this.logger.warn(
        `uploadDocument duplicate blocked filename="${normalizedName}" existingId=${duplicate.id} repository=${duplicate.currentRepository}`
      );
      throw new BadRequestException(
        `A document with filename "${normalizedName}" already exists (id: ${duplicate.id}, repository: ${duplicate.currentRepository}).`
      );
    }

    const documentId = uuidv4();
    const s3Key = `private-session/${documentId}/original.pdf`;
    this.logger.log(
      `uploadDocument start documentId=${documentId} userId=${userId} filename="${file.originalname}" sizeBytes=${file.size} mime=${file.mimetype}`
    );

    this.logger.log(`uploadDocument s3 put -> ${s3Key}`);
    await this.s3Service.uploadFile(s3Key, file.buffer, file.mimetype);
    this.logger.log(`uploadDocument s3 put done documentId=${documentId}`);

    const document = this.documentsRepository.create({
      id: documentId,
      originalFilename: file.originalname,
      s3Path: s3Key,
      currentRepository: DocumentRepository.PENDING_REVIEW,
      processingStatus: ProcessingStatus.UPLOADED,
      uploadedBy: userId
    });
    await this.documentsRepository.save(document);
    this.logger.log(`uploadDocument postgres row created documentId=${documentId}`);

    const queueUrl = process.env.SQS_QUEUE_URL;
    if (!queueUrl) {
      this.logger.warn(
        `uploadDocument SQS_QUEUE_URL not set, skipping enqueue. AI processing must be triggered manually for documentId=${documentId}`
      );
    } else {
      try {
        await sqsClient.send(
          new SendMessageCommand({
            QueueUrl: queueUrl,
            MessageBody: JSON.stringify({
              documentId,
              s3Path: s3Key,
              uploadedBy: userId
            })
          })
        );
        this.logger.log(`uploadDocument sqs enqueued documentId=${documentId}`);
      } catch (err: any) {
        this.logger.error(
          `uploadDocument sqs enqueue failed documentId=${documentId} error=${err?.message ?? err}`
        );
      }
    }

    this.logger.log(`uploadDocument done documentId=${documentId}`);
    return {
      documentId,
      filename: file.originalname,
      status: ProcessingStatus.UPLOADED,
      message: "Document uploaded and queued for processing."
    };
  }

  async listDocuments(filters: ListDocumentsDto) {
    // This function lists documents with optional status/repository filters.
    const page = filters.page || 1;
    const limit = filters.limit || 20;
    const query = this.documentsRepository.createQueryBuilder("documents");
    if (filters.repository) {
      query.andWhere("documents.current_repository = :repo", { repo: filters.repository });
    }
    if (filters.status) {
      query.andWhere("documents.processing_status = :status", { status: filters.status });
    }
    query.orderBy("documents.uploaded_at", "DESC").skip((page - 1) * limit).take(limit);
    const [data, total] = await query.getManyAndCount();
    return { data, total, page, limit };
  }

  async getDocument(id: string) {
    // This function returns one document or throws 404.
    const document = await this.documentsRepository.findOne({ where: { id } });
    if (!document) {
      throw new NotFoundException("Document not found");
    }
    return document;
  }

  async getPdfSignedUrl(id: string) {
    // This function returns a secure temporary URL for document PDF.
    const document = await this.getDocument(id);
    const url = await this.s3Service.getSignedUrl(document.s3Path, 300);
    return { url, expiresInSeconds: 300 };
  }

  async saveDocument(document: DocumentEntity) {
    // This function persists document changes made by review and pipeline modules.
    return this.documentsRepository.save(document);
  }
}
